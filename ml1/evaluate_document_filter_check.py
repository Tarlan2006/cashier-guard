"""Evaluate a frozen rejection filter on reviewed boxes, not whole-video ID checks."""
import argparse, hashlib, json
from pathlib import Path
from run_ollama_trial import ROOT, write_json
from import_document_search_review import validate


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_rows(rows, cutoff):
    positives=[];negatives=[];frames=[];unknown=0
    for row in rows:
        choice=row['human_selection'];props=row['proposals']
        for prop in props:
            predicted_rejection=prop['candidate_head_score']<=cutoff
            if predicted_rejection != (prop['selection_state']=='rejected_control'):
                raise ValueError('Frozen selection state disagrees with score')
        frame={'timestamp_sec':row['timestamp_sec'],'human_selection':choice}
        if choice=='none':
            rejected=sum(p['selection_state']=='rejected_control' for p in props)
            negatives.extend({'rejected':p['selection_state']=='rejected_control','frame_key':row['key']} for p in props)
            frame.update(incorrect_boxes_before=len(props),incorrect_boxes_retained=len(props)-rejected)
        elif choice in {'A','B','C'}:
            prop=props[ord(choice)-65];rejected=prop['selection_state']=='rejected_control'
            positives.append({'timestamp_sec':row['timestamp_sec'],'rejected':rejected,'head_score':prop['candidate_head_score']})
            frame.update(selected_correct_box_rejected=rejected)
            # The other boxes on a positive frame were not explicitly labeled.
        elif choice=='unclear': unknown+=1
        else:raise ValueError('Unexpected human answer')
        frames.append(frame)
    negative_frames=[r for r in frames if r['human_selection']=='none']
    return {'reviewed_frames':len(rows),'positive_reviewed_boxes':len(positives),
            'correct_boxes_retained':sum(not p['rejected'] for p in positives),'correct_boxes_rejected':sum(p['rejected'] for p in positives),
            'incorrect_reviewed_boxes':len(negatives),'incorrect_boxes_rejected':sum(p['rejected'] for p in negatives),
            'incorrect_boxes_retained':sum(not p['rejected'] for p in negatives),
            'negative_reviewed_frames_before_filter':len(negative_frames),
            'negative_reviewed_frames_with_remaining_incorrect_box':sum(r['incorrect_boxes_retained']>0 for r in negative_frames),
            'unclear_review_frames':unknown,'positive_box_details':positives,'frame_results':frames,
            'selection_biased_sample_not_population_accuracy':True,'scope':'displayed_reviewed_boxes_only',
            'document_absence_validated':False,'document_presentation_validated':False,'identity_verification_established':False,
            'legal_violation_label':None,'approved_for_rule_engine':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);args=parser.parse_args()
    trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local trial required')
    review_path=trial/'human-candidate-review.accepted.local.json';review=json.loads(review_path.read_text())
    validate(review,trial)
    if sha(trial/'human-candidate-review.original.local.json')!=review['review_sha256']:parser.error('Archived review changed')
    protocol=json.loads((trial/'protocol.local.json').read_text())
    if protocol['source_video_sha256'] in protocol['training_video_sha256'] or protocol['source_excluded_from_training'] is not True:
        parser.error('This is not a source held out from filter training')
    evaluation=evaluate_rows(review['reviews'],protocol['candidate_head_spec']['rejected_cutoff'])
    evaluation.update(source_video_sha256=protocol['source_video_sha256'],model_sha256=protocol['model_sha256'],
        reviewed_export_sha256=review['review_sha256'],source_excluded_from_training=True,
        model_retrained_on_this_review=False,model_frozen_before_review=protocol['model_frozen_before_this_candidate_review'])
    write_json(trial/'frozen-filter-evaluation.local.json',evaluation)
    pointer=ROOT/'local/document-filter-check-current.local.json';current=json.loads(pointer.read_text())
    if Path(current['trial']).resolve()==trial:
        write_json(pointer,{**current,'status':'human_review_evaluated','evaluation':str(trial/'frozen-filter-evaluation.local.json'),'approved_for_rule_engine':False})
    print('FROZEN_FILTER_CHECK_EVALUATED:',trial)
    print(json.dumps({k:v for k,v in evaluation.items() if k not in {'frame_results','positive_box_details'}}))


if __name__=='__main__':main()
