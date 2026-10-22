"""Bounded parent-side reads for a camera driver that may block inside read().

Only this disposable worker owns AVFoundation. Releasing it never calls a stuck
camera driver's release method in the application process.
"""
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import numpy as np

HEADER=struct.Struct('!IIId')


class IsolatedCapture:
    def __init__(self,index,command=None,clock=time.monotonic):
        self.clock=clock;self.frame_time=None;self.closed=False
        self.latest=None;self.serial=0;self.consumed=0;self.lock=threading.Lock()
        command=command or [sys.executable,str(Path(__file__).resolve()),'--worker',str(index),str(os.getpid())]
        self.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL,bufsize=0)
        self.reader=threading.Thread(target=self._receive,name=f'camera-frames-{index}',daemon=True)
        self.reader.start()

    def _exact(self,count):
        chunks=[]
        while count and not self.closed:
            data=self.process.stdout.read(count)
            if not data:return None
            chunks.append(data);count-=len(data)
        return b''.join(chunks) if not count else None

    def _receive(self):
        try:
            while not self.closed:
                header=self._exact(HEADER.size)
                if header is None:return
                height,width,channels,stamp=HEADER.unpack(header)
                if not (0<height<=4096 and 0<width<=4096 and channels==3 and np.isfinite(stamp)):return
                data=self._exact(height*width*channels)
                if data is None:return
                frame=np.frombuffer(data,dtype=np.uint8).reshape(height,width,channels).copy()
                with self.lock:
                    self.latest=(stamp,frame);self.serial+=1
        except (OSError,ValueError):
            return

    def isOpened(self):
        return not self.closed and self.process.poll() is None

    def read(self):
        with self.lock:
            if self.closed or self.latest is None or self.consumed==self.serial:return False,None
            self.consumed=self.serial;stamp,frame=self.latest
            if not 0<=self.clock()-stamp<.5:return False,None
            self.frame_time=stamp
            return True,frame

    def release(self):
        if self.closed:return
        self.closed=True
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    self.process.kill();self.process.wait(timeout=.5)
        except ProcessLookupError:pass
        self.process.stdout.close()
        self.reader.join(timeout=.2)
        with self.lock:self.latest=None


def worker(index,parent):
    # A crashed parent must not leave a camera-owning child behind.
    def watch_parent():
        while os.getppid()==parent:time.sleep(.5)
        os._exit(0)
    threading.Thread(target=watch_parent,daemon=True).start()
    import cv2
    camera=cv2.VideoCapture(index,cv2.CAP_AVFOUNDATION)
    if not camera.isOpened():return
    try:
        while True:
            ok,frame=camera.read()
            stamp=time.monotonic()
            if not ok or frame is None or not frame.size:
                time.sleep(.02);continue
            if frame.ndim!=3 or frame.shape[2]!=3:continue
            frame=np.ascontiguousarray(frame,dtype=np.uint8)
            sys.stdout.buffer.write(HEADER.pack(*frame.shape,stamp))
            sys.stdout.buffer.write(frame.tobytes());sys.stdout.buffer.flush()
    except (BrokenPipeError,KeyboardInterrupt):pass
    finally:camera.release()


if __name__=='__main__' and len(sys.argv)==4 and sys.argv[1]=='--worker':
    worker(int(sys.argv[2]),int(sys.argv[3]))
