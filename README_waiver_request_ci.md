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

### GitHub Actions Workflow: `.github/workflows/jfcli.yml`

The workflow `JF-CLI: Curation Waiver Request` triggers on every push to any branch. It defines **three independent jobs**, each demonstrating a different strategy for handling Curation-blocked packages in a pipeline.

#### Workflow-level configuration

```yaml
env:
  JF_RT_URL: "https://psazuse.jfrog.io"
  JFROG_CLI_LOG_LEVEL: DEBUG
  BUILD_NAME: "cwr"                          # CWR = Curation Waiver Request
  REPO_VIRTUAL: "curation-blocked-py-virtual"
  REPO_REMOTE:  "curation-blocked-py-remote"
```

| Variable | Purpose |
|---|---|
| `JF_RT_URL` | Base URL of the JFrog Platform instance |
| `JFROG_CLI_LOG_LEVEL` | Verbose CLI logging; useful for diagnosing waiver prompt failures |
| `BUILD_NAME` | Identifies this build in Artifactory |
| `REPO_VIRTUAL` | Virtual repository that aggregates the curation-blocked remote repo |
| `REPO_REMOTE` | The underlying remote repository; used to filter pending waivers by repo key |

---

### Job 1: `AutoSubmitWaiverRequest` — Auto-submit via `waiver_request_ci.py`

This job automatically submits a curation waiver request for all blocked packages using the PTY-based Python script.

#### Steps

**1. Setup JFrog CLI**
```yaml
- name: "Setup JFrog CLI"
  uses: jfrog/setup-jfrog-cli@v4
  with:
    version: latest
    oidc-provider-name: ${{vars.JF_OIDC_PROVIDER_NAME}}
```
Installs the latest JFrog CLI and authenticates using **OIDC** (no stored secrets).

**2. Checkout**
```yaml
- name: Checkout
  uses: actions/checkout@v4
```
Makes `requirements.txt` and `waiver_request_ci.py` available in the workspace.

**3. Create pip config**
```yaml
- name: "Create pip config"
  run: |
    jf pipc --repo-resolve=curation-blocked-py-virtual
```
Configures pip to resolve packages through the JFrog virtual repository. This routes all pip traffic through Curation so blocked packages are visible to `jf ca`.

**4. Waiver Request** ← _this is where `waiver_request_ci.py` is invoked_
```yaml
- name: "Waiver Request"
  run: |
    # Set CI=false to enable interactive prompts for waiver requests
    export CI=false
    python3 waiver_request_ci.py
    # Reset CI=true for subsequent steps
    export CI=true
```

- **`export CI=false`** — GitHub Actions sets `CI=true` by default, which causes the JFrog CLI to suppress all interactive prompts. Setting it to `false` re-enables the `"Do you want to request a waiver?"` prompt that `waiver_request_ci.py` depends on.
- **`python3 waiver_request_ci.py`** — runs the PTY-based automation script that:
  1. **Re-runs `jf ca` from scratch** — spawns its own `jf ca --requirements-file=requirements.txt --format=table --threads=100` inside a real PTY. It does **not** reuse output from any prior standalone `"Curation-Audit"` step; the two runs are fully independent.
  2. Waits for and detects `"Found N blocked packages"`
  3. Answers `y` to the waiver prompt
  4. Accepts `[all]` packages
  5. Submits a timestamped waiver reason (overridable via `WAIVER_REASON` env var)
  6. Confirms submission by detecting `"Waiver request submitted"` and the expected number of waiver IDs in the result table
- **`export CI=true`** — restores standard CI behaviour for any subsequent steps.

#### Flow diagram — Job 1

```
Push to any branch
       │
       ▼
┌─────────────────────┐
│  Setup JFrog CLI    │  ← OIDC auth, no stored secrets
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Checkout repo      │  ← requirements.txt + waiver_request_ci.py available
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  jf pipc            │  ← pip routed through curation-blocked-py-virtual
└────────┬────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│  export CI=false                             │
│  python3 waiver_request_ci.py                │
│   ├─ spawn PTY: jf ca ... --format=table     │
│   ├─ detect "Found N blocked packages"       │
│   ├─ answer "y" to waiver prompt             │
│   ├─ accept [all] packages                   │
│   ├─ send waiver reason                      │
│   └─ validate "Waiver request submitted" + N IDs │
│  export CI=true                              │
└──────────────────────────────────────────────┘
         │
         ▼
   ✅ Waiver IDs logged to console
```

---

### Job 2: `waiverExistsSkipNextSteps` — Skip install if waivers are pending

This job detects whether pending waiver requests already exist for the remote repo via the Xray REST API, and conditionally skips `pip install` if they do (to avoid re-triggering a blocked install mid-review cycle).

#### Steps

**1–2. Setup JFrog CLI + Checkout** — same as Job 1.

**3. Create PY config**
```yaml
- name: "Create PY config"
  run: |
    jf pipc --repo-resolve=${{env.REPO_VIRTUAL}} --repo-deploy=${{env.REPO_VIRTUAL}}
```
Configures both resolve and deploy through the virtual repo.

**4. Curation-Audit** _(diagnostic — output not captured)_
```yaml
- name: "Curation-Audit"
  run: |
    jf ca --format=table --threads=100
```
Runs `jf ca` to display the current audit results in the job log. This is a **read-only diagnostic step** — its output is printed to the log but not captured into a variable or passed to any subsequent step.

**5. Waiver pending info**
```yaml
- name: "Waiver pending info"
  env:
    CURL_URL: "${{env.JF_RT_URL}}/xray/ui/curation/waiver_requests?pkg_type=PyPI&status=pending&num_of_rows=100&direction=asc"
```
Calls the JFrog Xray REST API with the OIDC token to fetch all pending PyPI waiver requests. Filters results by `REPO_REMOTE` and:
- Writes a summary table to `$GITHUB_STEP_SUMMARY`
- Sets `WAIVER_REQUEST_EXISTS=TRUE` in `$GITHUB_ENV` if any match is found

**6. Pip install** _(conditional)_
```yaml
- name: "Pip install"
  if: ${{ env.WAIVER_REQUEST_EXISTS != 'TRUE' }}
  run: |
    jf pip install -r requirements.txt ...
```
Only runs if no pending waiver exists for `REPO_REMOTE`. Skipped entirely while waivers are under review.

#### Flow diagram — Job 2

```
Push to any branch
       │
       ▼
  Setup + Checkout + jf pipc
       │
       ▼
┌─────────────────────────────────────┐
│  jf ca --format=table               │  ← diagnostic only, output logged
└────────┬────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────┐
│  curl /xray/ui/curation/waiver_requests?status=pending│
│  filter by REPO_REMOTE                               │
│  write summary table → $GITHUB_STEP_SUMMARY          │
│  if match → WAIVER_REQUEST_EXISTS=TRUE               │
└────────┬─────────────────────────────────────────────┘
         │
         ▼
  WAIVER_REQUEST_EXISTS == TRUE?
    YES → skip pip install   NO → jf pip install -r requirements.txt
```

---

### Job 3: `waiverBlockingThePipeline` — Fail the build on blocked packages

This job uses `jf ca` as a **build gate**: if any blocked packages are detected, the job exits with an error and the build fails. It intentionally does not auto-submit a waiver — the developer must resolve the block before the pipeline can proceed.

#### Steps

**1–3. Setup JFrog CLI + Checkout + Create PY config** — same as Job 2.

**4. Curation-Audit** _(output captured — build gate)_
```yaml
- name: "Curation-Audit"
  run: |
    output=$(jf ca --format=table --threads=100)
    echo "$output"
    if echo "$output" | grep -q "blocked package"; then
      echo "::error::Build failed: Build contains blocked packages."
      exit 1
    fi
```
Unlike Job 2's `Curation-Audit`, here the output **is** captured into `$output`. The step:
- Prints the audit table to the log
- Greps for `"blocked package"` in the output
- Fails the build with a GitHub Actions error annotation (`::error::`) if any match is found

**5. Pip install — blocked packages**
```yaml
- name: "Pip install - blocked packages"
  run: |
    jf pip install -r requirements.txt --build-name ${{env.BUILD_NAME}} --build-number ${{env.BUILD_ID}}
```
Only reached if step 4 passed (no blocked packages detected).

#### Flow diagram — Job 3

```
Push to any branch
       │
       ▼
  Setup + Checkout + jf pipc
       │
       ▼
┌──────────────────────────────────────────┐
│  output=$(jf ca --format=table)          │
│  echo "$output"                          │
│  grep "blocked package"?                 │
│    YES → ::error:: + exit 1 ❌           │
│    NO  → continue ✅                     │
└────────┬─────────────────────────────────┘
         │ (no blocked packages)
         ▼
  jf pip install -r requirements.txt
```

---

#### Required GitHub repository configuration

| Setting | Where to configure | Value |
|---|---|---|
| `JF_OIDC_PROVIDER_NAME` | Settings → Variables → Actions | Name of the OIDC provider configured in JFrog |
| Workflow permissions | Settings → Actions → General | `id-token: write` (for OIDC), `contents: read` |

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
