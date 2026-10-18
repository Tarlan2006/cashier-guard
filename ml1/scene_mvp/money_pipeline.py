"""Bind local money experiments to their source, frozen code and human reviews."""
import hashlib,json,re
from pathlib import Path

TARGETS=('cash','cashier_hand','client_hand')
ANSWERS={'correct_on_reviewed_frames','incorrect_on_reviewed_frames','unclear'}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def frozen_check(root,profile):
    binding=profile.get('validation_plan')
    if not binding:
        return {'frozen_plan':False,'independent_accuracy_established':False}
    plan_id=binding.get('plan_id','')
    if not re.fullmatch(r'transfer-control-plan-[0-9-]+',plan_id):
        raise ValueError('Invalid transfer plan id')
    folder=(root/'local'/plan_id).resolve()
    if not folder.is_relative_to((root/'local').resolve()):
        raise ValueError('Plan outside local root')
    path=folder/'plan.local.json'
    if sha(path)!=binding.get('sha256'):
        raise ValueError('Transfer plan hash mismatch')
    plan=json.loads(path.read_text())
    for key in ('source_session','source_video_sha256'):
        if profile.get(key)!=plan.get(key):raise ValueError('Transfer plan source mismatch')
    if plan.get('expected_direction_supplied') is not False or plan.get('direction_labels_used') is not False:
        raise ValueError('Expected direction was used in the frozen plan')
    for name,digest in plan['code_sha256'].items():
        code=(root/name).resolve()
        if not code.is_relative_to(root.resolve()) or sha(code)!=digest:
            raise ValueError('Frozen transfer code changed: '+name)
    runtime=json.loads((root/'local/runtime/sam2-runtime.local.json').read_text())
    if runtime['source_revision']!=plan['sam_source_revision'] or runtime['weights_sha256']!=plan['sam_weights_sha256']:
        raise ValueError('Frozen SAM runtime changed')
    return {'frozen_plan':True,'plan_id':plan_id,'plan_sha256':sha(path),
            'different_from_development_video':profile['source_video_sha256']!=plan['development_video_sha256'],
            'expected_direction_supplied':False,'independent_accuracy_established':False,
            'review_blinded':False,'scope':'fixed_method_check_with_human_visual_prompts'}

def check_mask_review(review,trial_name,profile,observations):
    if review.get('schema_version')!=1 or review.get('review_session')!=trial_name:
        raise ValueError('Wrong mask review session')
    for key in ('source_session','source_video_sha256'):
        if review.get(key)!=profile[key]:raise ValueError('Mask review source mismatch')
    if review.get('confirmed') is False:raise ValueError('Mask review is a draft')
    if review.get('review_scope')!='user_reviewed_frames_only' or review.get('approved_for_rule_engine') is not False:
        raise ValueError('Mask review scope/approval mismatch')
    if review.get('transfer_candidates')!=observations['transfer_candidates']:
        raise ValueError('Reviewed predictions changed')
    answers=review.get('human_target_reviews',{})
    if set(answers)!=set(TARGETS) or any(answers[k] not in ANSWERS for k in TARGETS):
        raise ValueError('Three human mask answers required')
    return all(answers[k]=='correct_on_reviewed_frames' for k in TARGETS)
