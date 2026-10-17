"""Check local annotation structure without printing observations or reading video."""
import argparse
import json
import math
from pathlib import Path, PurePosixPath


def validate(data):
    errors = []
    event_ids, hashes, groups, filenames = set(), set(), set(), set()
    def check(ok, message):
        if not ok:
            errors.append(message)
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    check(data.get('schema_version') == 1, 'Unsupported schema_version')
    check(bool(data.get('videos')), 'No videos')
    for video in data.get('videos', []):
        group = video.get('content_group')
        check(group not in groups, 'Duplicate content group')
        groups.add(group)
        digest = video.get('sha256', '')
        check(len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'Invalid SHA256')
        check(digest not in hashes, 'Duplicate content stored as separate groups')
        hashes.add(digest)
        duration = video.get('duration_sec')
        if not number(duration) or duration <= 0:
            errors.append('Invalid video duration')
            continue
        check(video.get('split') in [None, 'development', 'validation', 'holdout'], 'Invalid split')
        check(video.get('full_video_review_status') in ['not_reviewed', 'reviewed'], 'Invalid full-video review status')
        for filename in video.get('files', []):
            check(filename not in filenames, 'Filename occurs in multiple groups')
            filenames.add(filename)
        for source in video.get('source_annotations', []):
            check(source.get('source_file') in video.get('files', []), 'Source annotation refers to another group')
        for event in video.get('events', []):
            event_id = event.get('event_id')
            check(bool(event_id) and event_id not in event_ids, 'Missing or duplicate event ID')
            event_ids.add(event_id)
            times = [event.get('timecode_sec')] + event.get('supporting_timecodes_sec', [])
            check(all(number(t) and 0 <= t <= duration for t in times), 'Event timestamp outside video duration')
            state = event.get('review_status')
            check(state in ['needs_review', 'reviewed_candidate', 'dismissed', 'insufficient_data'], 'Invalid event review status')
            if state != 'reviewed_candidate':
                continue
            check(bool(event.get('observation_local')) and bool(event.get('type_local')), 'Reviewed candidate lacks observation or type')
            refs = event.get('rule_references', [])
            check(bool(refs) and all(r.get('document') and r.get('url') and r.get('paragraph') for r in refs), 'Reviewed candidate lacks exact legal reference')
            check(event.get('conditions_checked') is True and event.get('exceptions_checked') is True, 'Conditions or exceptions not checked')
            check(type(event.get('is_omission')) is bool, 'Omission flag must be set')
            if event.get('is_omission'):
                start, end = event.get('context_start_sec'), event.get('context_end_sec')
                check(number(start) and number(end) and 0 <= start < end <= duration, 'Omission lacks a valid context interval')
                check(event.get('complete_operation_visible') is True, 'Omission lacks full-operation visibility check')
            frames = event.get('evidence_frames_local', [])
            check(1 <= len(frames) <= 3, 'Reviewed candidate must have 1–3 evidence frames')
            for frame in frames:
                time = frame.get('timestamp_sec')
                check(number(time) and 0 <= time <= duration, 'Evidence timestamp outside video duration')
                path = PurePosixPath(frame.get('path', ''))
                check(bool(frame.get('path')) and not path.is_absolute() and '..' not in path.parts, 'Evidence path must be relative without parent traversal')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default=str(Path(__file__).with_name('forte_annotations_draft.json')))
    parser.add_argument('--require-reviewed', action='store_true', help='Also reject unfinished manual review')
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.path).read_text(encoding='utf-8'))
        errors = validate(data)
        videos = data.get('videos', [])
        events = [event for video in videos for event in video.get('events', [])]
        unfinished_videos = sum(v.get('full_video_review_status') != 'reviewed' for v in videos)
        unfinished_events = sum(e.get('review_status') not in ['reviewed_candidate', 'dismissed'] for e in events)
        if args.require_reviewed and (unfinished_videos or unfinished_events):
            errors.append('Manual review is unfinished')
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print('Cannot validate: check the input file and JSON structure. No content printed.')
        return 1
    print(f'Video groups: {len(videos)}; event records: {len(events)}')
    print(f'Unfinished full-video reviews: {unfinished_videos}; unfinished event reviews: {unfinished_events}')
    if errors:
        for error in sorted(set(errors)):
            print('ERROR:', error)
        return 1
    print('Structure valid. This check does not verify video evidence or legal conclusions.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
