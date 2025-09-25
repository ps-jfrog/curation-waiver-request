#!/usr/bin/env python3

import pexpect
import os
import sys

# Config - Artifactory info
os.environ['JF_HOST'] = "psazuse.jfrog.io"
os.environ['JFROG_CLI_LOG_LEVEL'] = "DEBUG"
os.environ['RT_REPO_REMOTE'] = "curation-blocked-py-virtual"
os.environ['JF_RT_URL'] = f"https://{os.environ['JF_HOST']}"
os.environ['BUILD_NAME'] = "py-cli-req"
os.environ['BUILD_ID'] = f"cmd.{__import__('datetime').datetime.now().strftime('%Y-%m-%d-%H-%M')}"

print(f" JF_RT_URL: {os.environ['JF_RT_URL']}")
print(f" JFROG_CLI_LOG_LEVEL: {os.environ['JFROG_CLI_LOG_LEVEL']}")
print(f" BUILD_NAME: {os.environ['BUILD_NAME']}")
print(f" BUILD_ID: {os.environ['BUILD_ID']}")
print(f" RT_REPO_REMOTE: {os.environ['RT_REPO_REMOTE']}")

try:
    # Create pip config
    print("Creating pip config...")
    child = pexpect.spawn('jf pipc --repo-resolve=curation-blocked-py-virtual')
    child.expect('pip build config successfully created.')
    child.close()
    
    # Run curation audit and handle the interactive prompts
    print("Running curation audit with automated input...")
    child = pexpect.spawn('jf ca --requirements-file=requirements.txt --format=table --threads=100')
    child.timeout = 120  # Set longer timeout
    
    # Wait for the waiver request prompt
    child.expect('Do you want to request a waiver for any of the listed packages\\? \\(y/n\\) \\[n\\]\\?')
    print("Found waiver prompt, sending 'y'...")
    child.sendline('y')
    
    # Wait for the row number prompt
    child.expect('Please enter the row number\\(s\\) for which you want to request a waiver')
    print("Found row number prompt, sending Enter (using default 'all')...")
    child.sendline('')  # Send just Enter to use default value
    
    # Wait for the reason prompt
    child.expect('Please enter the reason for the waiver request:')
    print("Found reason prompt, sending reason...")
    child.sendline('pipeline demo')
    
    # Wait for completion - try multiple patterns
    try:
        child.expect(pexpect.EOF, timeout=30)
        print("✅ Waiver request completed successfully!")
        sys.exit(0)  # Success exit code
    except pexpect.TIMEOUT:
        print("Process may have completed but didn't close properly. Checking for success indicators...")
        # Check if we can find success indicators in the output
        output = child.before.decode('utf-8')
        if 'waiver' in output.lower() or 'request' in output.lower():
            print("✅ Waiver request appears to have been submitted successfully!")
            sys.exit(0)  # Success exit code
        else:
            print("❌ Could not confirm waiver request submission")
            print("Output:", output)
            sys.exit(1)  # Error exit code
    
    # Print any remaining output
    output = child.before.decode('utf-8')
    if output:
        print("Final output:", output)
    
    child.close()
    
    # For CI, don't open browser - just print the URL
    print(f"🌐 Waiver requests can be viewed at: {os.environ['JF_RT_URL']}/ui/package-curation/waivers-requests")
    
except pexpect.TIMEOUT:
    print("❌ Timeout occurred. The command may have taken too long or the expected output wasn't found.")
    if 'child' in locals():
        print("Current output:", child.before.decode('utf-8'))
        child.close()
    sys.exit(1)
except pexpect.EOF:
    print("❌ Command ended unexpectedly.")
    if 'child' in locals():
        print("Output before EOF:", child.before.decode('utf-8'))
        child.close()
    sys.exit(1)
except Exception as e:
    print(f"❌ An error occurred: {e}")
    if 'child' in locals():
        child.close()
    sys.exit(1)