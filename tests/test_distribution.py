import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import select
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import launcher
import install as installer
import rag

class TTY(io.StringIO):
    def isatty(self):return True

class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='localcg-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)/'home with spaces'
        self.home.mkdir()
        self.bin=Path(self.tmp.name)/'backends';self.bin.mkdir()
        self.fake=self.bin/'agent'
        self.fake.write_text('#!/usr/bin/python3\nimport os,json,sys\nprint(json.dumps({"args":sys.argv[1:],"mode":os.getenv("AGENT_COMPUTE_MODE"),"home":os.getenv("HERMES_HOME"),"base":os.getenv("LOCAL_C_GPU_BASE_URL"),"config":os.getenv("OPENCODE_CONFIG_CONTENT")}))\n')
        self.fake.chmod(0o755)
        self.env={**os.environ,'HOME':str(self.home)}
        self.command=[sys.executable,str(ROOT/'src/install.py'),'--no-start']
        for name in ('ollama','hermes','opencode'):self.command += ['--'+name+'-bin',str(self.fake)]

    def install(self,*args,ok=True):
        p=subprocess.run(self.command+list(args),env=self.env,text=True,capture_output=True)
        self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr)
        return p

    def test_install_reinstall_preserves_private_config(self):
        self.install()
        config=self.home/'.local/share/local-c-gpu/hermes/config.yaml'
        generated=json.loads(config.read_text())
        self.assertEqual(generated['tools']['tool_search']['enabled'],'off')
        self.assertEqual(generated['model']['ollama_num_ctx'],65536)
        config.write_text('PRIVATE SENTINEL\n')
        self.install()
        self.assertEqual(config.read_text(),'PRIVATE SENTINEL\n')
        for app in ('hermes','opencode'):
            for suffix in ('','-cpu','-gpu'):
                self.assertTrue((self.home/'.local/bin'/(app+suffix)).is_symlink())
        self.assertIn('CUDA_VISIBLE_DEVICES=-1',(self.home/'.config/systemd/user/local-c-gpu-cpu.service').read_text())
        self.assertNotIn('CUDA_VISIBLE_DEVICES=-1',(self.home/'.config/systemd/user/local-c-gpu-gpu.service').read_text())

    def test_conflict_fails_without_touching_original(self):
        target=self.home/'.local/bin/hermes';target.parent.mkdir(parents=True);target.write_text('original')
        self.install(ok=False)
        self.assertEqual(target.read_text(),'original')
        self.assertFalse((self.home/'.config/local-c-gpu/settings.json').exists())
        self.install('--replace-commands')
        self.assertEqual(target.with_name('hermes.before-local-c-gpu').read_text(),'original')

    def test_replacing_upstream_entry_preserves_callable_backend(self):
        for kind in ('symlink','file'):
            with self.subTest(kind=kind):
                target=self.home/'.local/bin/hermes'
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink():target.unlink()
                if kind=='symlink':target.symlink_to(self.fake)
                else:
                    target.write_bytes(self.fake.read_bytes());target.chmod(0o755)
                self.install('--hermes-bin',str(target),'--replace-commands')
                result=subprocess.run([str(target),'--version'],env=self.env,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['args'],['--version'])
                self.install()
                again=subprocess.run([str(target),'--version'],env=self.env,text=True,capture_output=True)
                self.assertEqual(again.returncode,0,again.stderr)
                target.with_name('hermes.before-local-c-gpu').unlink()

    def test_reinstall_preserves_custom_mcp(self):
        self.install()
        p=self.home/'.config/local-c-gpu/settings.json'
        config=json.loads(p.read_text())
        config['rag_enabled']=True
        config['rea_bin']=str(self.fake)
        custom={name:{'type':'local','enabled':False,'command':['custom-command']} for name in ('local-docs','rea')}
        config['opencode_mcp']=custom
        p.write_text(json.dumps(config))
        self.install()
        self.assertEqual(json.loads(p.read_text())['opencode_mcp'],custom)

    def test_invalid_ports_and_missing_backend_fail_before_writes(self):
        self.install('--cpu-port','0',ok=False)
        self.install('--cpu-port','12435',ok=False)
        self.install('--hermes-bin','/nonexistent/agent',ok=False)
        self.install('--pull',ok=False)
        self.assertFalse((self.home/'.local/share/local-c-gpu').exists())

    def test_real_pty_menu_invalid_input_and_cancel(self):
        self.install()
        for app in ('hermes','opencode'):
            master,slave=pty.openpty()
            proc=subprocess.Popen([str(self.home/'.local/bin'/app)],stdin=slave,stdout=slave,stderr=slave,env=self.env)
            os.close(slave)
            try:
                output=b''
                deadline=time.monotonic()+5
                while b'[1]:' not in output and time.monotonic()<deadline:
                    if select.select([master],[],[],0.2)[0]:output+=os.read(master,4096)
                self.assertIn('CPU'.encode(),output);self.assertIn('GPU'.encode(),output)
                os.write(master,b'bad\nq\n')
                proc.wait(timeout=5)
                output+=os.read(master,4096)
                self.assertIn('1, 2'.encode(),output)
                self.assertEqual(proc.returncode,0)
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
                os.close(master)

    def test_passthrough_uses_real_backend_and_independent_homes(self):
        self.install()
        for app in ('hermes','opencode'):
            p=subprocess.run([str(self.home/'.local/bin'/app),'--version'],env=self.env,text=True,capture_output=True,check=True)
            result=json.loads(p.stdout)
            self.assertEqual(result['args'],['--version'])
            self.assertTrue(result['home'].startswith(str(self.home)))

    def test_menu_choices_and_boundaries(self):
        for text,expected in [('1\n','cpu'),('2\n','gpu'),('\n','cpu'),('bad\n2\n','gpu'),('q\n',None),('',None)]:
            self.assertEqual(launcher.choose_mode(TTY(text),io.StringIO()),expected)
        self.assertEqual(launcher.choose_mode(io.StringIO('2\n'),io.StringIO()),'cpu')

    def test_routing_preserves_arguments_and_custom_mcp(self):
        self.install()
        with patch.object(launcher,'SETTINGS',self.home/'.config/local-c-gpu/settings.json'):
            launcher.load_settings()
            for app in ('hermes','opencode'):
                for mode,port in [('cpu','12434'),('gpu','12435')]:
                    env=launcher.environment(app,mode,{'OPENCODE_CONFIG_CONTENT':'{"mcp":{"other":{"enabled":true}}}'})
                    self.assertIn(port,env['LOCAL_C_GPU_EMBED_URL'])
                    if app=='hermes':self.assertIn(port,env['LOCAL_C_GPU_BASE_URL'])
                    else:self.assertIn('other',json.loads(env['OPENCODE_CONFIG_CONTENT'])['mcp'])
                    args=['--resume','session123','literal $(touch nope)']
                    self.assertEqual(launcher.command(app,mode,args)[-3:],args)

    def test_service_port_probe_handles_active_and_time_wait_sockets(self):
        server=socket.socket()
        server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind(('127.0.0.1',0));server.listen(1)
        port=server.getsockname()[1]
        unit=installer.service(str(self.fake),self.home/'models',port,'cpu')
        line=next(x for x in unit.splitlines() if x.startswith('ExecStartPre='))
        command=shlex.split(line.split('=',1)[1])
        client=socket.create_connection(('127.0.0.1',port))
        conn,_=server.accept()
        try:
            busy=subprocess.run(command,capture_output=True)
            self.assertNotEqual(busy.returncode,0)
            conn.shutdown(socket.SHUT_WR)
            self.assertEqual(client.recv(1),b'')
            conn.close();client.close();server.close()
            free=subprocess.run(command,capture_output=True)
            self.assertEqual(free.returncode,0,free.stderr)
        finally:
            conn.close();client.close();server.close()

    def test_rag_roundtrip_excludes_hidden_and_symlink_files(self):
        docs=self.home/'docs';docs.mkdir()
        (docs/'robot.md').write_text('robot safety torque off')
        (docs/'.private.txt').write_text('SECRET')
        secret=self.home/'secret.md';secret.write_text('SECRET')
        (docs/'linked.md').symlink_to(secret)
        with patch.dict(os.environ,{'LOCAL_C_GPU_DATA':str(self.home/'data')}),patch.object(rag,'embed',return_value=[[1.0,0.0]]):
            self.assertEqual(rag.build(docs),1)
            result=rag.search_documents('robot',1)
            self.assertEqual(result[0]['path'],'robot.md')
            self.assertEqual(rag.read_document('robot.md'),'robot safety torque off')
            with self.assertRaises(ValueError):rag.read_document('../secret.md')
            with self.assertRaises(ValueError):rag.search_documents(' ',1)
            with self.assertRaises(ValueError):rag.search_documents('robot',0)
            with patch.object(rag,'embed',side_effect=RuntimeError('server down')):
                with self.assertRaises(RuntimeError):rag.build(docs)
            self.assertEqual(rag.read_document('robot.md'),'robot safety torque off')

if __name__=='__main__':unittest.main(verbosity=2)
