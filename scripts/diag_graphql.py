"""Diagnostic only: which GraphQL stargazer shape the workflow token can read."""
import json
import os

import requests

H = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
Q = {
    "a_count_only": 'query{repository(owner:"omacom",name:"omarchy"){stargazerCount}}',
    "b_last2_starredAt": 'query{repository(owner:"omacom",name:"omarchy"){stargazers(last:2,orderBy:{field:STARRED_AT,direction:ASC}){edges{starredAt}}}}',
    "c_last2_with_node": 'query{repository(owner:"omacom",name:"omarchy"){stargazers(last:2,orderBy:{field:STARRED_AT,direction:ASC}){edges{starredAt node{createdAt}}}}}',
    "d_last2_no_order": 'query{repository(owner:"omacom",name:"omarchy"){stargazers(last:2){edges{starredAt}}}}',
    "e_first2_order": 'query{repository(owner:"omacom",name:"omarchy"){stargazers(first:2,orderBy:{field:STARRED_AT,direction:DESC}){edges{starredAt}}}}',
}
for k, q in Q.items():
    r = requests.post("https://api.github.com/graphql", json={"query": q}, headers=H, timeout=30)
    print(k, r.status_code, json.dumps(r.json())[:400], flush=True)
