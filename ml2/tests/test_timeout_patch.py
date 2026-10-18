"""Apply the proposed backend patch to a temporary copy and test its behavior."""
import ast
import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import httpx

ROOT=Path(__file__).resolve().parents[1]


class PipelineError(Exception):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


class TimeoutPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.copy=tempfile.TemporaryDirectory()
        root=Path(cls.copy.name);target=root/'backend/app/pipeline.py'
        target.parent.mkdir(parents=True)
        shutil.copyfile(ROOT.parent/'backend/app/pipeline.py',target)
        subprocess.run(['git','apply',str(ROOT/'patches/backend-ml-timeouts.patch')],
            cwd=root,check=True,capture_output=True)
        tree=ast.parse(target.read_text(encoding='utf-8'))
        names={'ML_REQUEST_TIMEOUT_SECONDS','ML2_REQUEST_TIMEOUT_SECONDS',
               'ML1_READ_TIMEOUT_SECONDS','ML2_READ_TIMEOUT_SECONDS','MAX_ML_RESPONSE_BYTES'}
        nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
        nodes += [node for node in tree.body if
            (isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in node.targets))
            or (isinstance(node,ast.AsyncFunctionDef) and node.name in {'_request_json','analyze'})]
        cls.code=compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'patched_pipeline.py','exec')

    @classmethod
    def tearDownClass(cls):
        cls.copy.cleanup()

    def scope(self):
        values=dict(asyncio=asyncio,httpx=httpx,json=json,PipelineError=PipelineError)
        exec(self.code,values)
        return values

    def test_total_deadlines_are_stage_specific_and_errors_remain_errors(self):
        async def run(stage):
            values=self.scope()
            values['ML_REQUEST_TIMEOUT_SECONDS']=.01 if stage=='ml1' else .5
            values['ML2_REQUEST_TIMEOUT_SECONDS']=.01 if stage=='ml2' else .5
            async def slow(request):
                await asyncio.sleep(.1)
                return httpx.Response(200,json={})
            async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
                with self.assertRaises(PipelineError) as error:
                    await values['_request_json'](client,'http://localhost/test',stage)
                self.assertEqual(error.exception.code,stage.upper()+'_TIMEOUT')
        for stage in ('ml1','ml2'):
            with self.subTest(stage=stage):asyncio.run(run(stage))

    def test_live_analysis_passes_separate_read_limits(self):
        values=self.scope();seen={}
        async def request(client,url,stage,**kwargs):
            seen[stage]=kwargs['timeout'].read
            return {}
        values.update(math=__import__('math'),monotonic=__import__('time').monotonic,
            load_rules=lambda _:[],_request_json=request,
            _validate_observations=lambda *_:SimpleNamespace(model_dump=lambda:dict(schema_version='1.0',events=[])),
            _validate_result=lambda *_:dict(verdict='no_violation',violations=[]))
        settings=SimpleNamespace(mode='live',rules_path=Path('unused'),
            ml1_url='http://localhost:8001',ml2_url='http://localhost:8002')
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'video.mp4';video.write_bytes(b'synthetic transport bytes')
            result=asyncio.run(values['analyze'](video,10,settings,'unused',lambda _:None))
        self.assertEqual(seen,dict(ml1=180,ml2=30))
        self.assertEqual(result,dict(verdict='no_violation',violations=[]))
        self.assertEqual(values['ML_REQUEST_TIMEOUT_SECONDS'],190)
        self.assertEqual(values['ML2_REQUEST_TIMEOUT_SECONDS'],35)


if __name__=='__main__':unittest.main()
