#!/usr/bin/env python3
import subprocess
import os
import sys

def test_hermes_direct():
    """Test calling hermes directly"""
    print("Testing direct hermes call...")
    
    prompt = "Find 2 Data Engineer jobs in Egypt. Return JSON: [{\"title\":\"\",\"company\":\"\",\"location\":\"\",\"url\":\"\",\"source\":\"\"}]"
    
    env = os.environ.copy()
    env['TERM'] = 'dumb'
    env['CI'] = '1'
    
    try:
        proc = subprocess.Popen(
            ['hermes', 'chat', '-q', prompt, '-t', 'web', '--provider', 'openrouter', '-Q'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            env=env
        )
        
        stdout, stderr = proc.communicate(timeout=30)
        print(f"Return code: {proc.returncode}")
        print(f"Stdout length: {len(stdout)}")
        print(f"Stderr length: {len(stderr)}")
        if stdout:
            print(f"Stdout preview: {stdout[:200]}")
        if stderr:
            print(f"Stderr preview: {stderr[:200]}")
            
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        print("TIMEOUT")
        print(f"Stdout: {stdout[:200] if stdout else ''}")
        print(f"Stderr: {stderr[:200] if stderr else ''}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_hermes_direct()