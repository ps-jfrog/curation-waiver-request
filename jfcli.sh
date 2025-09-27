# TOKEN SETUP
# jf c add --user=krishnam --interactive=true --url=https://psazuse.jfrog.io --overwrite=true 

# Config - Artifactory info
export JF_HOST="psazuse.jfrog.io"  JFROG_CLI_LOG_LEVEL="DEBUG" RT_REPO_REMOTE="curation-blocked-py-virtual"  # "curation-blocked-py-remote" # curation-blocked-py-virtual
export JF_RT_URL="https://${JF_HOST}" BUILD_NAME="py-cli-req" BUILD_ID="cmd.$(date '+%Y-%m-%d-%H-%M')" 

echo " JF_RT_URL: $JF_RT_URL \n JFROG_CLI_LOG_LEVEL: $JFROG_CLI_LOG_LEVEL \n "
echo " BUILD_NAME: $BUILD_NAME \n BUILD_ID: $BUILD_ID \n RT_REPO_REMOTE: $RT_REPO_REMOTE"

jf pipc --repo-resolve=${RT_REPO_REMOTE} 

jf ca --requirements-file=requirements.txt --format=table --threads=100 

# Do you want to request a waiver for any of the listed packages? (y/n) [n]? 



open -a "Google Chrome" ${JF_RT_URL}/ui/package-curation/waivers-requests