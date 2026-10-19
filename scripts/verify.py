"""One command: real tests -> offline smoke -> ablations -> agent checks -> evidence report."""
import argparse
import os
import subprocess
import sys

from scripts.common import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deepseek',action='store_true',help='Also run paid real DeepSeek integration tests if a key exists')
    args = parser.parse_args()
    env = {**os.environ,'KO_RUN_LIVE_TESTS':'0','KO_RUN_DEEPSEEK_TESTS':'1' if args.deepseek else '0',
           'KO_MODE':'offline','KO_LLM_PROVIDER':'auto','PYTHONUTF8':'1'}
    if args.deepseek:
        env['KO_DEEPSEEK_TEST_DATA_DIR'] = str(ROOT/'data'/'deepseek_validation'/'index')
    commands = [
        ['ruff','check','src','tests','scripts'],
        ['pytest','-q','--tb=short','--junitxml=reports/pytest.xml','--cov=knowledgeops',
         '--cov-report=json:reports/coverage.json','--cov-report=xml:reports/coverage.xml'],
        ['scripts.smoke','--mode','offline'],
        ['scripts.evaluate_retrieval','--mode','offline'],
        ['scripts.evaluate_agent','--mode','offline'],
        ['scripts.build_report'],
        ['scripts.check_secrets'],
    ]
    for command in commands:
        print('VERIFY:', ' '.join(command), flush=True)
        subprocess.run([sys.executable,'-m',*command],cwd=ROOT,env=env,check=True)


if __name__ == '__main__':
    main()
