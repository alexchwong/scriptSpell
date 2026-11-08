"""Usage: python scripts/check_adversarial.py [--report reports/adversarial.json]."""
import argparse
import socket
import tempfile
from pathlib import Path
from feasibility_support import run_case, report, blocked_case


def main(argv=None):
    p=argparse.ArgumentParser(description='Run controlled attacks with synthetic secrets and detect external effects.')
    p.add_argument('--report',default='reports/adversarial.json')
    args=p.parse_args(argv)
    try: import psutil
    except ImportError:
        return report('adversarial', [blocked_case('dependencies', 'install_dev_dependencies')], args.report)
    results=[]
    with tempfile.TemporaryDirectory(prefix='scriptspell-check-') as folder:
        secret=Path(folder)/'secret.txt'; secret.write_text('SYNTHETIC_SECRET')
        marker=Path(folder)/'unexpected.txt'
        listener=socket.socket()
        try:
            listener.bind(('127.0.0.1',0)); listener.listen(32); listener.setblocking(False)
            port=listener.getsockname()[1]
        except OSError:
            listener.close()
            return report('adversarial', [blocked_case('loopback', 'listener_unavailable')], args.report)
        raw=[
            ('raw_file_read', f'open({str(secret)!r}).read()'),
            ('raw_file_write', f'open({str(marker)!r}, "w").write("unexpected")'),
            ('raw_environment', 'import os\nos.environ["HOME"]'),
            ('raw_process', f'import subprocess\nsubprocess.run(["touch", {str(marker)!r}])'),
            ('raw_network', f'import socket\nsocket.create_connection(("127.0.0.1", {port}))'),
            ('raw_dns', 'import socket\nsocket.getaddrinfo("localhost", 80)'),
            ('raw_print_flood', 'while True:\n    print("x" * 1000)'),
        ]
        public=[
            ('policy_eval', 'def transform(inputs):\n    return {"out": eval("1")}','source_rejected'),
            ('policy_reflection','def transform(inputs):\n    return {"out": inputs.__class__}','source_rejected'),
            ('policy_print','def transform(inputs):\n    print(inputs)\n    return {"out": 1}','source_rejected'),
            ('policy_reserved','def transform(inputs):\n    _ss_outputs = []\n    return {"out": 1}','source_rejected'),
            ('infinite_loop','def transform(inputs):\n    while True:\n        pass','limit_exceeded'),
            ('recursion','def transform(inputs):\n    return transform(inputs)','limit_exceeded'),
            ('unsupported_function','def transform(inputs):\n    return {"out": transform}','invalid_result'),
            ('cyclic_result','def transform(inputs):\n    a = []\n    a.append(a)\n    return {"out": a}','invalid_result'),
            ('deep_result','def transform(inputs):\n    a = []\n    for i in range(40):\n        a = [a]\n    return {"out": a}','invalid_result'),
            ('stop','def transform(inputs):\n    while True:\n        pass','cancelled'),
            ('deadline','def transform(inputs):\n    while True:\n        pass','deadline'),
            ('worker_crash','def transform(inputs):\n    while True:\n        pass','worker_crash'),
        ]
        cases=[dict(name=n,source=s,raw=True) for n,s in raw]
        cases += [dict(name=n,source=s,expected=[e],cancel=n=='stop',crash=n=='worker_crash',wall_seconds=0.15 if n=='deadline' else 5) for n,s,e in public]
        try:
            for case in cases:
                r=run_case(case)
                connections=0
                while True:
                    try:
                        c,_=listener.accept(); c.close(); connections+=1
                    except BlockingIOError: break
                if connections or marker.exists() or secret.read_text()!='SYNTHETIC_SECRET':
                    r.update(status='FAIL',reason='unexpected_host_effect')
                results.append(r)
        finally: listener.close()
    return report('adversarial',results,args.report)

if __name__=='__main__': raise SystemExit(main())
