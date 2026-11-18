"""Exact frame/value pairing, clock bounds, and diagnostic session lifecycle."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
import cv2
import numpy as np
from diagnostic_recording import CameraRecording
import diagnostic_recording as recording
import session_recorder as sessions
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer


class DiagnosticRecordingTest(unittest.TestCase):
    def test_status_and_legacy_replay_omit_repeated_packets_but_keep_every_beam(self):
        from diagnostic_snapshot import compact_state, compact_record
        packet={'pixels':list(range(2000))}
        rays=[dict(id=i,eye=[.1,.2],head=[0,0,0,.5,.5,.2],target=[.5,.5],
                   source='cursor',captured_at=i,paired_eyes={'left':packet},head_sample=packet)
              for i in range(400)]
        state={'desktop_gaze':[500,300],'onboarding':{'calibration_rays':rays,'calibration_log':'audit.jsonl'}}
        slim=compact_state(state)
        self.assertLess(len(json.dumps(slim)),len(json.dumps(state))/50)
        self.assertEqual(len(slim['onboarding']['calibration_rays']),400)
        for original,beam in zip(rays,slim['onboarding']['calibration_rays']):
            for field in ('id','eye','head','target','source','captured_at'):
                self.assertEqual(beam[field],original[field])
        self.assertIs(state['onboarding']['calibration_rays'][0]['head_sample'],packet)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'gaze.jsonl'
            path.write_text(json.dumps(dict(t_ms=100,tracker_state=state))+'\n')
            loaded=sessions.load_lines(path,compact_record)
            self.assertEqual(loaded[0]['tracker_state'],slim)
            self.assertIn('head_sample',json.loads(path.read_text())['tracker_state']['onboarding']['calibration_rays'][0])
            with path.open('a') as output:
                output.write(json.dumps(dict(t_ms=133,tracker_state=state))+'\n')
            loaded=sessions.load_gaze(path)
            self.assertIs(loaded[0]['tracker_state']['onboarding']['calibration_rays'],
                          loaded[1]['tracker_state']['onboarding']['calibration_rays'])

    def test_two_face_streams_keep_distinct_frames_and_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin=time.monotonic();capture=CameraRecording(tmp,origin,'test')
            capture.submit('face',origin+.01,np.zeros((12,12,3),np.uint8),None,{'camera_id':'built'})
            capture.submit('face_secondary',origin+.02,np.full((12,12,3),220,np.uint8),None,{'camera_id':'fhd'})
            self.assertEqual(capture.finish()['frames'],{'face':1,'face_secondary':1})
            primary=sessions.load_lines(Path(tmp)/'face-frames.jsonl')[0]
            secondary=sessions.load_lines(Path(tmp)/'face_secondary-frames.jsonl')[0]
            self.assertEqual(primary['values']['camera_id'],'built')
            self.assertEqual(secondary['values']['camera_id'],'fhd')
            self.assertTrue(secondary['raw'].endswith('.jpg'))
            with zipfile.ZipFile(Path(tmp)/'camera-frames.zip') as archive:
                self.assertNotEqual(archive.read(primary['raw']),archive.read(secondary['raw']))

    def test_rejected_frame_is_lossless_and_keeps_its_own_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin=time.monotonic()
            capture=CameraRecording(tmp,origin,'test')
            frame=np.arange(30*40*3,dtype=np.uint8).reshape(30,40,3)
            expected=frame.copy()
            values={'accepted':False,'detector':{'confidence':.12,'pupil_ellipse':{'center':[13.,19.]},'bad':float('nan')}}
            capture.submit('left',origin+.09,frame,None,values)
            values['detector']['pupil_ellipse']['center'][0]=999
            frame[:]=0
            capture.submit('right',origin+.11,expected,None,{'accepted':True})
            capture.submit('face',origin+.12,expected,None,{'packet':{'pose':None}})
            summary=capture.finish()
            self.assertEqual(summary['frames'],{'left':1,'right':1,'face':1})
            row=json.loads((Path(tmp)/'left-frames.jsonl').read_text())
            self.assertAlmostEqual(row['t_ms'],90,places=4)
            self.assertFalse(row['values']['accepted'])
            self.assertEqual(row['values']['detector']['pupil_ellipse']['center'],[13.,19.])
            self.assertIsNone(row['values']['detector']['bad'])
            with zipfile.ZipFile(Path(tmp)/'camera-frames.zip') as archive:
                saved=cv2.imdecode(np.frombuffer(archive.read(row['raw']),np.uint8),cv2.IMREAD_COLOR)
            np.testing.assert_array_equal(saved,expected)
            self.assertEqual(capture.finish(),summary)

    def test_does_not_record_outside_window_or_after_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin=time.monotonic();capture=CameraRecording(tmp,origin,'test')
            frame=np.zeros((10,10,3),np.uint8)
            capture.submit('left',origin-.01,frame,None,{})
            capture.submit('left',origin+60.01,frame,None,{})
            capture.submit('invalid',origin+.1,frame,None,{})
            self.assertEqual(capture.finish()['frames'],{})
            capture.submit('left',origin+.1,frame,None,{})
            self.assertEqual((Path(tmp)/'left-frames.jsonl').read_text(),'')

    def test_one_minute_cap_finalizes_even_without_stop_request(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(recording,'LIMIT_SECONDS',.05):
            capture=CameraRecording(tmp,time.monotonic(),'test')
            capture.timer.join(timeout=2)
            self.assertTrue(capture.closed)
            self.assertFalse(capture.worker.is_alive())
            self.assertIsNotNone(capture.summary)

    def test_camera_only_session_needs_no_calibration_or_screen_permission(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sessions,'RECORDINGS',Path(tmp)),patch.object(recording,'ROOT',Path(tmp)),patch.object(sessions,'read_state',return_value={'calibrated':False}),patch.object(sessions,'displays',side_effect=AssertionError('Screen access not requested')):
            def command(action,body):
                if action=='record-start':
                    recording.begin(body['session_id'],body['origin_monotonic']);return {}
                return recording.finish(body['session_id'])
            with patch.object(sessions,'tracker_command',side_effect=command):
                manager=sessions.SessionManager();manifest=manager.start()
                active=manager.active;origin=active['origin']
                recording.publish('right',origin+.01,np.zeros((12,12,3),np.uint8),None,{'accepted':False})
                # Same callback used by the automatic stop timer.
                manager._auto_stop(manifest['id'])
                self.assertIsNone(manager.active)
                loaded=sessions.session_data(Path(tmp)/manifest['id'])
                self.assertFalse(loaded['manifest']['has_screen'])
                self.assertEqual(len(loaded['cameras']['right']),1)
                self.assertEqual(manager.status()['last_finished'],manifest['id'])
                self.assertLessEqual(loaded['manifest']['duration_ms'],60000)

    def test_new_recording_replaces_previous_only_after_successful_start(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sessions,'RECORDINGS',Path(tmp)),patch.object(sessions,'read_state',return_value={}),patch.object(sessions,'tracker_command',return_value={}):
            unrelated=Path(tmp)/'notes';unrelated.mkdir();(unrelated/'keep.txt').write_text('keep')
            manager=sessions.SessionManager()
            first=manager.start();manager.stop()
            old_folder=Path(tmp)/first['id']
            (old_folder/'camera-frames.zip').write_bytes(b'old recording')
            with patch.object(sessions,'tracker_command',side_effect=RuntimeError('Camera unavailable')):
                with self.assertRaises(RuntimeError):manager.start()
            self.assertTrue(old_folder.exists())
            self.assertIsNone(manager.active)
            second=manager.start()
            try:
                self.assertFalse(old_folder.exists())
                self.assertEqual([row['id'] for row in sessions.saved_sessions()],[second['id']])
                self.assertEqual((unrelated/'keep.txt').read_text(),'keep')
            finally:manager.stop()
            self.assertEqual(manager.status()['last_finished'],second['id'])

    def test_pause_omits_frames_and_keeps_active_timeline_contiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin=time.monotonic()-1
            capture=CameraRecording(tmp,origin,'test')
            frame=np.zeros((12,12,3),np.uint8)
            capture.submit('left',origin+.5,frame,None,{})
            capture.pause(True,origin+.6)
            capture.submit('left',origin+.8,frame,None,{})
            capture.pause(False,origin+1.1)
            capture.submit('left',origin+1.2,frame,None,{})
            self.assertEqual(capture.finish()['frames'],{'left':2})
            rows=sessions.load_lines(Path(tmp)/'left-frames.jsonl')
            self.assertAlmostEqual(rows[0]['t_ms'],500,places=3)
            self.assertAlmostEqual(rows[1]['t_ms'],700,places=3)

    def test_replay_pairs_frame_state_and_displayed_cursor_without_prediction(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sessions,'RECORDINGS',Path(tmp)):
            sid='20261027T120000-1234abcd';folder=Path(tmp)/sid;folder.mkdir()
            (folder/'session.json').write_text(json.dumps(dict(id=sid,status='complete',duration_ms=1000)))
            (folder/'gaze.jsonl').write_text(json.dumps(dict(t_ms=100,tracker_state={'desktop_gaze':[999,999]}))+'\n')
            (folder/'presentation.jsonl').write_text(json.dumps(dict(t_ms=100,cursors={'combined':dict(point=[20,30],opacity=.5)},scene={'width':30}))+'\n')
            with zipfile.ZipFile(folder/'camera-frames.zip','w') as archive:
                for side in ('left','right','face','face_secondary'):
                    name=f'{side}/000000.png';archive.writestr(name,b'frame-'+side.encode())
                    (folder/f'{side}-frames.jsonl').write_text(json.dumps(dict(t_ms=100,preview=name))+'\n')
            try:
                frame=sessions.replay_frame(sid,100)
                self.assertEqual(frame['cursors']['combined']['point'],[20,30])
                self.assertEqual(frame['state']['desktop_gaze'],[999,999])
                self.assertEqual(len(frame['images']),4)
                self.assertEqual(sessions.replay_timeline(sid)['frames'],[100])
                gap=sessions.replay_frame(sid,800)
                self.assertEqual(gap['images'],{})
                self.assertEqual(gap['cursors'],{})
                self.assertIsNone(gap['state'])
                self.assertEqual(sessions.replay_frame(sid,100)['cursors'],frame['cursors'])
            finally:sessions.replay_data.cache_clear();sessions.camera_archive.cache_clear()

    def test_http_replay_returns_exact_frame_and_blocks_arbitrary_paths(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sessions,'RECORDINGS',Path(tmp)):
            sid='20261027T120000-1234abcd';folder=Path(tmp)/sid;folder.mkdir()
            (folder/'session.json').write_text(json.dumps({'id':sid,'status':'complete'}))
            with zipfile.ZipFile(folder/'camera-frames.zip','w') as archive:archive.writestr('left/000000.png',b'known-image')
            server=ThreadingHTTPServer(('127.0.0.1',0),sessions.make_handler(sessions.SessionManager()))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                with urlopen(base+f'/api/sessions/{sid}/image/left/000000.png') as response:
                    self.assertEqual(response.read(),b'known-image')
                    self.assertEqual(response.headers['Content-Type'],'image/png')
                with self.assertRaises(HTTPError) as error:urlopen(base+f'/api/sessions/{sid}/image/../../session.json')
                self.assertEqual(error.exception.code,404)
            finally:server.shutdown();server.server_close();sessions.camera_archive.cache_clear()


if __name__=='__main__':unittest.main()
