"""Local acceptance probes using artificial images only. Never opens bank data."""
import base64
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

from run_ollama_trial import ROOT, MODEL, SMOL_MODEL, QWEN_MODEL, LOCAL_OLLAMA, request, synthetic_frames, write_json

CANONICAL = 'cashier-smolvlm:canonical'
TEMPLATE = ('<|im_start|>{{ if .System }}System: {{ .System }}<end_of_utterance>\n{{ end }}'
            'User:{{ .Prompt }}<end_of_utterance>\nAssistant:{{ .Response }}<end_of_utterance>')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ollama-bin',type=Path)
    parser.add_argument('--image-wrap',action='store_true',help='Probe SmolVLM image boundary tokens through chat API')
    parser.add_argument('--model',choices=(SMOL_MODEL,QWEN_MODEL),default=MODEL)
    args=parser.parse_args()
    port = 11436
    folder = ROOT/'local'/('quality-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    _, frames = synthetic_frames(folder)
    images = [base64.b64encode((folder/f['file']).read_bytes()).decode() for f in frames]
    red_folder=folder/'red';red_folder.mkdir()
    _,red_frames=synthetic_frames(red_folder,color=(255,0,0))
    red=base64.b64encode((red_folder/red_frames[0]['file']).read_bytes()).decode()
    env = {k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')}
    env.update({'OLLAMA_HOST':f'127.0.0.1:{port}', 'OLLAMA_MODELS':str(ROOT/'models'/'ollama'),
                'OLLAMA_NO_CLOUD':'1', 'OLLAMA_NUM_PARALLEL':'1', 'OLLAMA_MAX_LOADED_MODELS':'1',
                'OLLAMA_DEBUG_LOG_REQUESTS':'false'})
    # Refuse to use an existing server.
    import socket
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1',port))
    with (folder/'server.log').open('w') as log:
        executable=str(args.ollama_bin.resolve()) if args.ollama_bin else (str(LOCAL_OLLAMA) if LOCAL_OLLAMA.is_file() else 'ollama')
        server = subprocess.Popen([executable,'serve'], env=env, stdout=log, stderr=log)
    results = []
    try:
        deadline=time.monotonic()+60
        while True:
            try:
                version=request(port,'version',timeout=2)['version'];break
            except OSError:
                if server.poll() is not None or time.monotonic()>deadline:raise
                time.sleep(.2)
        assert 'Ollama cloud disabled: true' in (folder/'server.log').read_text()
        assert args.model in [x['name'] for x in request(port,'tags')['models']]
        models=[args.model]
        if args.model==SMOL_MODEL:
            request(port,'create',{'model':CANONICAL,'from':SMOL_MODEL,'template':TEMPLATE,'stream':False})
            models.append(CANONICAL)
        elif args.image_wrap:
            raise ValueError('SmolVLM boundary tokens do not apply to Qwen')
        motion='The images are in time order. Does the blue square move left, move right, or stay still?'
        cases=[('position_left',[images[0]],'Is the blue square on the left or right? Answer one word.','left'),
               ('position_right',[images[1]],'Is the blue square on the left or right? Answer one word.','right'),
               ('color_blue',[images[0]],'What color is the square?','blue'),
               ('color_red',[red],'What color is the square?','red'),
               ('forward',images,motion,'right'),('reverse',images[::-1],motion,'left'),
               ('stationary',[images[0],images[0]],motion,'still')]
        for model in models:
            for name,pictures,prompt,expected in cases:
                for structured in ([False,True] if len(pictures)>1 else [False]):
                    payload={'model':model,'prompt':prompt,'images':pictures,'stream':False,'keep_alive':'30s',
                             'options':{'temperature':0,'seed':1,'num_predict':1024 if model==QWEN_MODEL else 64,'num_ctx':4096 if model==QWEN_MODEL else 2048}}
                    if model==QWEN_MODEL:payload['think']=False
                    if structured:
                        payload['prompt'] += ' Return JSON with key direction.'
                        payload['format']={'type':'object','properties':{'direction':{'type':'string','enum':['left','right','still']}},
                                           'required':['direction'],'additionalProperties':False}
                    if args.image_wrap:
                        wrapped=''.join('<fake_token_around_image><global-img>[img]<fake_token_around_image>' for _ in pictures)
                        payload['messages']=[{'role':'user','content':wrapped+'\n'+payload.pop('prompt'),'images':payload.pop('images')}]
                        response=request(port,'chat',payload)
                        text=response.get('message',{}).get('content','').strip()
                    else:
                        response=request(port,'generate',payload)
                        text=response.get('response','').strip()
                    answer=None
                    if structured:
                        try:answer=json.loads(text)['direction']
                        except (ValueError,KeyError,TypeError):pass
                    else:
                        pattern=r'\b(blue|red)\b' if name.startswith('color_') else r'\b(left|right|still)\b'
                        tokens=re.findall(pattern,text.lower())
                        if len(set(tokens))==1:answer=tokens[0]
                        elif re.search(r'from (?:the )?left to (?:the )?right',text.lower()):answer='right'
                        elif re.search(r'from (?:the )?right to (?:the )?left',text.lower()):answer='left'
                        if name=='stationary' and re.search(r'no (?:visible )?change|(?:does not|doesn.t) move|same position|stays? still',text.lower()):answer='still'
                        if re.search(r'(?:top to bottom|bottom to top|up and down)',text.lower()):answer=None
                    required=structured or name.startswith(('position_','color_'))
                    item={'model':model,'case':name,'structured':structured,'expected':expected,'required':required,
                          'response':text,'answer':answer,'pass':answer==expected and response.get('done_reason')!='length',
                          'done_reason':response.get('done_reason'),'eval_count':response.get('eval_count'),
                          'thinking_chars':len(response.get('thinking',''))}
                    results.append(item)
                    write_json(folder/'results.json',{'artificial_only':True,'runtime_version':version,
                               'image_wrap':args.image_wrap,'results':results})
                    print(json.dumps(item),flush=True)
            request(port,'generate',{'model':model,'keep_alive':0})
        summary={m:{'passed':sum(x['pass'] for x in results if x['model']==m),
                    'total':sum(x['model']==m for x in results),
                    'passed_required':sum(x['pass'] for x in results if x['model']==m and x['required']),
                    'required_total':sum(x['model']==m and x['required'] for x in results)} for m in models}
        write_json(folder/'summary.json',{'runtime_version':version,'image_wrap':args.image_wrap,'scores':summary})
        print('SUMMARY',json.dumps(summary),flush=True)
        print('ARTIFICIAL_RESULTS',folder,flush=True)
    finally:
        try:request(port,'generate',{'model':args.model,'keep_alive':0},timeout=5)
        except Exception:pass
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':main()
