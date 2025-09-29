# Waiver Request CI Script

## Overview

The `waiver_request_ci.py` script is a robust Python automation tool designed to handle JFrog CLI curation waiver requests in automated environments, particularly CI/CD pipelines. It solves the critical issue where the JFrog CLI's interactive prompts fail in non-TTY environments.

## The Problem: TTY Requirements

The JFrog CLI uses the `go-prompt` library for interactive prompts, which requires a proper TTY (terminal) to function correctly. When run in automated environments using:

- `expect` scripts
- stdin redirection (`< input.txt`)
- CI/CD pipelines without proper TTY allocation
- Docker containers without TTY flags

The CLI crashes with errors like:
```
device not configured
```

## The Solution: Custom PTY Implementation

This script implements a custom pseudo-terminal (PTY) solution that:

1. **Creates a real TTY environment** using Python's `pty` module
2. **Handles interactive prompts** by simulating terminal input/output
3. **Provides robust error handling** with detailed logging
4. **Works in any environment** including CI/CD pipelines

## How It Works

### 1. PTY Setup
```python
def spawn_pty(cmd: str, extra_env=None):
    env = os.environ.copy()
    if extra_env: env.update(extra_env)
    pid, mfd = pty.fork()
    if pid == 0:
        argv = ["/bin/bash", "-lc", cmd]
        os.execvpe(argv[0], argv, env)
    set_winsize(mfd)
    return pid, mfd
```

The script creates a pseudo-terminal that:
- Forks a child process running the JFrog CLI command
- Sets up proper terminal dimensions
- Provides a file descriptor for bidirectional communication

### 2. Interactive Flow Handling

The script follows this precise sequence:

1. **Wait for Y/N prompt**: `"Do you want to request a waiver for any of the listed packages? (y/n) [n]?"`
2. **Send 'y'**: Accepts the waiver request
3. **Handle row selection**: Waits for and accepts the default `[all]` option
4. **Provide reason**: Sends a configurable waiver reason
5. **Wait for completion**: Monitors for success indicators

### 3. Robust Pattern Matching

```python
def wait_for_regex(mfd, pattern, buf, timeout):
    rx = re.compile(pattern, re.I | re.S)
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([mfd], [], [], 0.1)
        if r:
            if not read_some(mfd, buf, echo=True):
                break
            if rx.search("".join(buf)):
                return True
    return False
```

The script uses:
- **Regex pattern matching** to identify specific prompts
- **Timeout handling** to prevent infinite waits
- **Buffer management** to capture all output
- **Echo functionality** to show real-time progress

### 4. Success Validation

The script validates success by:
- Detecting "Waiver request submitted" messages
- Extracting waiver IDs from result tables
- Counting expected vs. actual waiver requests
- Providing detailed error messages on failure

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JF_CMD` | `"jf"` | JFrog CLI command name |
| `REQ_FILE` | `"requirements.txt"` | Requirements file path |
| `RT_REPO_REMOTE` | `"curation-blocked-py-virtual"` | Repository name |
| `JFROG_CLI_LOG_LEVEL` | `"DEBUG"` | CLI logging level |
| `TIMEOUT_SEC` | `120` | Overall timeout in seconds |
| `WAIVER_REASON` | Auto-generated | Waiver request reason |

### Example Usage

```bash
# Basic usage
python3 waiver_request_ci.py

# With custom configuration
export WAIVER_REASON="Production deployment waiver"
export TIMEOUT_SEC=180
python3 waiver_request_ci.py

# In CI/CD pipeline
export JF_HOST="your-jfrog-instance.com"
export JF_RT_URL="https://your-jfrog-instance.com"
python3 waiver_request_ci.py
```

## CI/CD Integration

### GitHub Actions Example

```yaml
- name: "Waiver Request"
  run: | 
    # Set CI=false to enable interactive prompts for waiver requests
    export CI=false
    python3 waiver_request_ci.py
    # Reset CI=true for subsequent steps
    export CI=true
```

### Docker Example

```dockerfile
# Ensure TTY is available
RUN python3 waiver_request_ci.py
```

Or run with TTY:
```bash
docker run -it --rm your-image python3 waiver_request_ci.py
```

## Error Handling

The script provides comprehensive error handling:

### Common Issues and Solutions

1. **"Did not reach the Y/N waiver prompt"**
   - **Cause**: CLI didn't find blocked packages or network issues
   - **Solution**: Check JFrog CLI configuration and network connectivity

2. **"Waiver table incomplete"**
   - **Cause**: Timeout or CLI didn't complete submission
   - **Solution**: Increase `TIMEOUT_SEC` or check JFrog platform status

3. **"Device not configured"**
   - **Cause**: PTY creation failed
   - **Solution**: Ensure script runs with proper permissions

### Debugging

Enable verbose output:
```bash
export JFROG_CLI_LOG_LEVEL=DEBUG
python3 waiver_request_ci.py
```

## Advantages Over Alternatives

### vs. `expect` Scripts
- ✅ **No external dependencies** (expect not always available)
- ✅ **Better error handling** with detailed diagnostics
- ✅ **Cross-platform compatibility** (works on Windows with WSL)

### vs. stdin Redirection
- ✅ **Works with TTY-requiring applications**
- ✅ **Handles complex interactive flows**
- ✅ **Provides real-time feedback**

### vs. Simple Automation
- ✅ **Robust pattern matching**
- ✅ **Timeout handling**
- ✅ **Success validation**

## Technical Details

### Dependencies
- Python 3.6+
- Standard library only (no external packages required)
- Unix-like system (Linux, macOS, WSL)

### Architecture
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Main Script   │───▶│   PTY Manager    │───▶│  JFrog CLI      │
│                 │    │                  │    │                 │
│ - Configuration │    │ - TTY Creation   │    │ - Curation      │
│ - Flow Control  │    │ - Input/Output   │    │ - Waiver        │
│ - Error Handling│    │ - Pattern Match  │    │ - Submission    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Performance
- **Typical runtime**: 30-60 seconds
- **Memory usage**: Minimal (< 10MB)
- **Network**: Depends on JFrog platform response time

## Troubleshooting

### Check Prerequisites
```bash
# Verify JFrog CLI is installed and configured
jf c s

# Test manual curation audit
jf ca --requirements-file=requirements.txt --format=table --threads=100
```

### Common Fixes
1. **Increase timeout**: `export TIMEOUT_SEC=300`
2. **Check network**: Verify JFrog platform accessibility
3. **Update CLI**: Ensure latest JFrog CLI version
4. **Check permissions**: Verify repository access rights

## Contributing

When modifying this script:

1. **Test in multiple environments** (local, CI, Docker)
2. **Maintain backward compatibility** with existing configurations
3. **Update error messages** to be helpful and actionable
4. **Add logging** for debugging complex issues

## License

This script is part of the curation-waiver-request project and follows the same licensing terms.
