"""Sequential local object analysis; SAM 2.1 is the selected default tracker."""
import argparse,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--calibration',nargs='+',type=Path,required=True)
 p.add_argument('--engine',choices=['sam2','edgetam'],default='sam2')
 args=p.parse_args();python=ROOT/'local/perception-venv/bin/python'
 if not python.exists():p.error('Local perception Python environment is missing')
 script=ROOT/('run_sam2_object_trial.py' if args.engine=='sam2' else 'run_edgetam_object_trial.py')
 for calibration in args.calibration:
  if not calibration.is_file():p.error('Calibration does not exist: '+str(calibration))
 for calibration in args.calibration:
  print('OBJECT_ANALYSIS_ENGINE:',args.engine,'INPUT:',calibration.name,flush=True)
  subprocess.run([str(python),str(script),'--calibration',str(calibration.resolve())],check=True,cwd=ROOT.parent)

if __name__=='__main__':main()
