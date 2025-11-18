# TOKEN SETUP
# jf c add --user=krishnam --interactive=true --url=https://psazuse.jfrog.io --overwrite=true 

# Config - Artifactory info
export JF_HOST="psazuse.jfrog.io"  JFROG_CLI_LOG_LEVEL="DEBUG" 
export RT_REPO_VIRTUAL="curation-blocked-py-virtual"  # krishnam-py-virtual 
export RT_REPO_REMOTE="curation-blocked-py-remote"        # pypi-remote 
export JF_RT_URL="https://${JF_HOST}" BUILD_NAME="py-cli-req" BUILD_ID="cmd.$(date '+%Y-%m-%d-%H-%M')" 

echo " JF_RT_URL: $JF_RT_URL \n JFROG_CLI_LOG_LEVEL: $JFROG_CLI_LOG_LEVEL \n "
echo " BUILD_NAME: $BUILD_NAME \n BUILD_ID: $BUILD_ID \n RT_REPO_REMOTE: $RT_REPO_VIRTUAL \n RT_REPO_REMOTE: $RT_REPO_REMOTE"

jf pipc --repo-resolve=${RT_REPO_VIRTUAL} 

jf ca --requirements-file=requirements.txt --format=table --threads=100 

# Do you want to request a waiver for any of the listed packages? (y/n) [n]? 

CURL_URL="${JF_RT_URL}/xray/ui/curation/waiver_requests?pkg_type=PyPI&status=pending&num_of_rows=100&direction=asc"
RESP_JSON="WAIVER_PENDING_RESP-${BUILD_ID}.json"
JF_WAIVER_URL="${JF_RT_URL}/ui/package-curation/waivers-requests"
WAIVER_PENDING_RESP=$(curl "${CURL_URL}" -H "Authorization: Bearer ${JF_ACCESS_TOKEN}")
echo $WAIVER_PENDING_RESP > ${RESP_JSON}

echo " | Waiver ID | Package Name | Package version | Requested on | Justification | Decision Owners | "
echo " | :--- | :--- | :--- | :--- | :--- | :--- | "
JSON_FILE="${RESP_JSON}"

jq -c '.data[]' "$JSON_FILE" | while read -r item; do
    # Check if any policy.repo_include contains TARGET_REPO
    # repo_match=$(echo "$item" | jq -r --arg repo "${REPO_REMOTE}" '.policies[] | select(.repo_include | index($repo))')
    # if [[ -z "$repo_match" ]]; then
    # continue  # skip this item if repo not included
    # fi

    waiver_id=$(echo "$item" | jq -r '.id')
    repo_key=$(echo "$item" | jq -r '.repo_key')

    pkg_name=$(echo "$item" | jq -r '.pkg_name')
    pkg_version=$(echo "$item" | jq -r '.pkg_version')

    # Extract decision owners (as comma-separated string)
    decision_owners=$(echo "$item" | jq -r '.decision_owners | join(", ")')

    # Extract most recent requester details
    latest_request=$(echo "$item" | jq -r '.requesters | sort_by(.requested_at) | last')
    requested_at=$(echo "$latest_request" | jq -r '.requested_at')
    justification=$(echo "$latest_request" | jq -r '.justification')

    # echo "REPO_REMOTE: ${RT_REPO_REMOTE}    repo_key: ${repo_key} "
    if [[ ("${RT_REPO_REMOTE}" == "${repo_key}") ]] ; then
        echo " |  ${waiver_id} | ${pkg_name} | ${pkg_version} | ${requested_at} | ${justification} | ${decision_owners} | "
    fi
done

rm -rf $RESP_JSON
# open -a "Google Chrome" ${JF_RT_URL}/ui/package-curation/waivers-requests

jf pip install -r requirements.txt --build-name $BUILD_NAME --build-number $BUILD_ID
echo "Pip install completed"

jf rt u dist/ pypi/