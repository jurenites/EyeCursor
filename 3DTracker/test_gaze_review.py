import unittest
from gaze_review import analyze
from session_recorder import research_sample


def point(t,x=.3,y=.4,confidence=.9,**extra):
    return dict(t_ms=t,x=x,y=y,confidence=confidence,valid=True,**extra)


class ReviewTests(unittest.TestCase):
    def test_returning_low_score_spike_is_flagged_without_changing_source(self):
        rows=[point(0),point(33,x=.9,confidence=.4),point(66)]
        result=analyze(rows,1000,700)
        self.assertEqual(result['points'][1]['status'],'possible_glitch')
        self.assertEqual(rows[1]['x'],.9)
        self.assertEqual(result['points'][1]['t_ms'],33)

    def test_fast_sustained_move_keeps_first_position_and_original_time(self):
        rows=[point(0),point(33,x=.8,confidence=.4),point(66,x=.8),point(99,x=.8)]
        result=analyze(rows,1000,700)
        self.assertTrue(all(p['status']=='measured' for p in result['points']))
        self.assertEqual(result['points'][1]['x'],.8)
        self.assertEqual(result['points'][1]['t_ms'],33)

    def test_high_confidence_out_and_back_is_not_silently_deleted(self):
        result=analyze([point(0),point(33,x=.9),point(66)],1000,700)
        self.assertEqual(result['points'][1]['status'],'measured')

    def test_dwell_uses_time_not_frame_count(self):
        for step in (20,40):
            result=analyze([point(t) for t in range(0,401,step)],1000,700)
            self.assertEqual(result['summary']['fixation_ms'],400)
            self.assertEqual(len(result['fixations']),1)

    def test_blinks_gaps_held_calibration_and_duplicates_do_not_create_dwell(self):
        rows=[point(t,capture_id=str(t)) for t in range(0,201,40)]
        rows += [point(240,held=True),point(280,learning=True),dict(t_ms=320,valid=False)]
        rows += [point(t,capture_id=str(t)) for t in range(400,601,40)]
        rows += [point(640,capture_id='600'),point(680,capture_id='600')]
        result=analyze(rows,1000,700)
        self.assertEqual([f['duration_ms'] for f in result['fixations']],[200,200])
        result=analyze([point(0),point(1000),point(2000)],1000,700)
        self.assertEqual(result['fixations'],[])

    def test_range_and_offscreen_do_not_snap_to_a_reading_area(self):
        rows=[point(t) for t in range(0,1001,40)]
        result=analyze(rows,1000,700,200,600)
        self.assertEqual(result['summary']['fixation_ms'],400)
        self.assertEqual(analyze([point(t,x=1.2) for t in range(0,400,40)],1000,700)['fixations'],[])

    def test_independent_eye_capture_is_unfenced_and_uses_selected_display(self):
        state=dict(mode='hybrid',gaze_eye_mode='both',tracking_viewport=[1000,0,1000,800],
                   raw_eye_predictions={
                       'left':dict(uv=[1.1,.4],confidence=.9,captured_at=10,held=False),
                       'right':dict(uv=[1.3,.4],confidence=.8,captured_at=10.01,held=False)})
        row=research_sample(state,dict(x=1000,y=0,width=2000,height=1600,point_width=1000,point_height=800))
        self.assertAlmostEqual(row['x'],1.2)
        self.assertAlmostEqual(row['y'],.4)
        self.assertEqual(row['confidence'],.8)
        state['raw_eye_predictions']['right']['held']=True
        self.assertAlmostEqual(research_sample(state)['x'],1.1)
        state['raw_eye_predictions']['left']['held']=True
        self.assertFalse(research_sample(state)['valid'])

    def test_unsynchronized_eyes_cannot_form_a_research_sample(self):
        state=dict(mode='hybrid',raw_eye_predictions={
            'left':dict(uv=[.2,.4],confidence=.9,captured_at=1),
            'right':dict(uv=[.8,.4],confidence=.9,captured_at=2)})
        self.assertFalse(research_sample(state)['valid'])

    def test_old_prediction_during_a_rejected_frame_is_not_a_fixation_sample(self):
        state=dict(mode='hybrid',raw_eye_predictions={
            'left':dict(uv=[.2,.4],confidence=.9,captured_at=1)},
            eye_cameras={'eyes':{'left':{'measurement_valid':False}}})
        self.assertFalse(research_sample(state)['valid'])


if __name__=='__main__': unittest.main()
