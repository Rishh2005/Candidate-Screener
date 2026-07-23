import re
import requests
from typing import Dict, Any

def extract_github_username(url: str) -> str:
    if not url or str(url).strip().lower() in ['none', 'nan', '']:
        return None
    match = re.search(r'github\.com/([a-zA-Z0-9_-]+)', str(url))
    return match.group(1) if match else None

def analyze_github_profile(github_url: str, token: str = None) -> Dict[str, Any]:
    username = extract_github_username(github_url)
    if not username:
        return {"error": "Invalid or missing GitHub profile link"}
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    try:
        # User profile endpoint
        user_res = requests.get(f"https://api.github.com/users/{username}", headers=headers, timeout=10)
        if user_res.status_code != 200:
            return {"error": f"User not found on GitHub (Status {user_res.status_code})"}
        user_data = user_res.json()
        
        # Repositories endpoint
        repos_res = requests.get(f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated", headers=headers, timeout=10)
        repos = repos_res.json() if repos_res.status_code == 200 else []
        
        total_stars = sum(r.get("stargazers_count", 0) for r in repos)
        total_forks = sum(r.get("forks_count", 0) for r in repos)
        
        languages = {}
        top_repos = []
        for r in sorted(repos, key=lambda x: x.get("stargazers_count", 0), reverse=True)[:5]:
            lang = r.get("language")
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            top_repos.append({
                "name": r.get("name"),
                "description": r.get("description"),
                "stars": r.get("stargazers_count"),
                "language": r.get("language"),
                "url": r.get("html_url")
            })
            
        return {
            "username": username,
            "public_repos": user_data.get("public_repos", 0),
            "followers": user_data.get("followers", 0),
            "total_stars": total_stars,
            "total_forks": total_forks,
            "top_languages": list(languages.keys()),
            "top_repositories": top_repos
        }
    except Exception as e:
        return {"error": f"GitHub API error: {str(e)}"}