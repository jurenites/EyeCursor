"""Small UI snapshots; full calibration evidence remains in the audit journal.

Do not repeat every saved camera/head packet in every 30 Hz status response.
Keep all displayed ray geometry and its identity, without mutating solver data.
"""


def compact_state(state):
    onboarding = state.get('onboarding')
    if not isinstance(onboarding, dict) or 'calibration_rays' not in onboarding:
        return state
    rays = [{key: value for key, value in row.items()
             if key not in ('paired_eyes', 'head_sample')}
            for row in onboarding['calibration_rays']]
    return dict(state, onboarding=dict(onboarding, calibration_rays=rays))


def compact_record(row):
    state = row.get('tracker_state')
    return dict(row, tracker_state=compact_state(state)) if isinstance(state, dict) else row
