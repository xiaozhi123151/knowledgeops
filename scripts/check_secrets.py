"""Check known local provider secrets against tracked/unignored project files without printing them."""
import os
import subprocess

from dotenv import dotenv_values

from scripts.common import ROOT


def main():
    env = {**dotenv_values(ROOT/'.env'),**os.environ}
    keys = ['DEEPSEEK_API_KEY','KO_DEEPSEEK_API_KEY','KO_LLM_API_KEY','KO_EMBEDDING_API_KEY']
    secrets = [env[k].encode() for k in keys if env.get(k) and len(env[k])>=16]
    acceptance = dotenv_values(ROOT/'data/acceptance/service.env')
    secrets += [str(value).encode() for name,value in acceptance.items()
                if ('KEY' in name or 'SECRET' in name) and value and len(value)>=16]
    result = subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],
                            cwd=ROOT,capture_output=True,check=True)
    leaks = []
    for name in result.stdout.decode('utf-8').split('\0'):
        path = ROOT/name
        if name and path.is_file() and any(secret in path.read_bytes() for secret in secrets):
            leaks.append(name)
    if leaks:
        print('SECRET_LEAK_DETECTED in: '+', '.join(leaks))
        raise SystemExit(1)
    print('Secret scan passed: no configured provider key in tracked/unignored project files.')


if __name__ == '__main__':
    main()
