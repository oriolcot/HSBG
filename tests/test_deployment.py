import os,subprocess,tempfile,pathlib,unittest,shutil
script=str(pathlib.Path('scripts/deploy-remote.sh').resolve())
def run(*args,**kw): return subprocess.run(args,check=True,capture_output=True,text=True,**kw).stdout.strip()

@unittest.skipUnless(os.name == "posix" and all(shutil.which(x) for x in ("bash", "git", "flock", "timeout")), "Deployment target requires Linux tools")
class DeploymentTests(unittest.TestCase):
 def test_success_and_verified_recovery(self):
  for scenario in ['success','restart-failure','health-failure']:
   with tempfile.TemporaryDirectory() as tmp:
    root=pathlib.Path(tmp);origin=root/'origin';repo=root/'repo';bin=root/'bin';bin.mkdir()
    run('git','init','-b','main',str(origin));run('git','-C',str(origin),'config','user.name','Test');run('git','-C',str(origin),'config','user.email','test@example.invalid')
    (origin/'version').write_text('old');run('git','-C',str(origin),'add','version');run('git','-C',str(origin),'commit','-m','old');old=run('git','-C',str(origin),'rev-parse','HEAD')
    run('git','clone',str(origin),str(repo));(origin/'version').write_text('new');run('git','-C',str(origin),'commit','-am','new');new=run('git','-C',str(origin),'rev-parse','HEAD')
    (bin/'sudo').write_text('#!/bin/bash\nif [[ "$SCENARIO" == restart-failure && $(cat version) == new ]]; then exit 1; fi\nexit 0\n')
    (bin/'curl').write_text('''#!/bin/bash
  if [[ "$SCENARIO" == health-failure && $(cat version) == new ]]; then printf '{"status":"ok"}\\n503'; else printf '{"status":"ok"}\\n200'; fi
  ''')
    (bin/'sleep').write_text('#!/bin/bash\nexit 0\n')
    for p in bin.iterdir():p.chmod(0o755)
    env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH'],'SCENARIO':scenario}
    r=subprocess.run(['bash',script,str(repo),'example-service',new],env=env,capture_output=True,text=True)
    head=run('git','-C',str(repo),'rev-parse','HEAD')
    assert r.returncode==(0 if scenario=='success' else 1),(scenario,r.stdout,r.stderr)
    assert head==(new if scenario=='success' else old),(scenario,head)
    if scenario!='success':assert 'restored and health verified' in r.stderr,r.stderr
    print('PASS:',scenario)
