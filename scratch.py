def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow MCP token if present
        if request.headers.get("Authorization") and request.headers.get("X-MCP-Access-Token"):
            return require_oauth_access_token(f)(*args, **kwargs)
        # Otherwise, require UI session
        return require_ui_auth(f)(*args, **kwargs)
    return decorated_function
