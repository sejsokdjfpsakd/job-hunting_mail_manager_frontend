document.addEventListener('DOMContentLoaded', async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const state = urlParams.get('state');
  const clientName = urlParams.get('client_name') || 'An application';
  const callbackUrl = urlParams.get('callback');
  
  if (!state || !callbackUrl) {
    document.getElementById('consent-error').textContent = 'Invalid request parameters.';
    document.getElementById('approve-btn').disabled = true;
    return;
  }
  
  document.getElementById('client-name').textContent = clientName;
  
  // First, verify session to ensure user is logged in
  try {
    const res = await fetch('/api.cgi/api/auth/me');
    if (!res.ok) throw new Error('Not logged in');
  } catch (e) {
    // If not logged in, redirect to login page (we can just redirect to index.html and they'll have to restart the flow)
    // We pass the current URL as a redirect parameter so they come back here after login
    window.location.href = 'index.html?redirect=' + encodeURIComponent(window.location.href);
    return;
  }
  
  function getCsrfToken() {
    const name = "session_id=";
    const decodedCookie = decodeURIComponent(document.cookie);
    const ca = decodedCookie.split(';');
    for(let i = 0; i <ca.length; i++) {
      let c = ca[i];
      while (c.charAt(0) == ' ') c = c.substring(1);
      if (c.indexOf(name) == 0) return c.substring(name.length, c.length);
    }
    return "";
  }

  document.getElementById('approve-btn').addEventListener('click', async () => {
    try {
      const res = await fetch('/api.cgi/api/oauth/consent/approve', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken()
        },
        body: JSON.stringify({ state, client_name: clientName })
      });
      const result = await res.json();
      
      if (result.success && result.token) {
        // Redirect to callback URL with token
        const redirectUrl = new URL(callbackUrl);
        redirectUrl.searchParams.set('token', result.token);
        if (state) redirectUrl.searchParams.set('state', state);
        window.location.href = redirectUrl.toString();
      } else {
        throw new Error(result.error || 'Failed to approve');
      }
    } catch (e) {
      document.getElementById('consent-error').textContent = e.message;
    }
  });

  document.getElementById('deny-btn').addEventListener('click', () => {
    // Redirect to callback URL with error
    const redirectUrl = new URL(callbackUrl);
    redirectUrl.searchParams.set('error', 'access_denied');
    if (state) redirectUrl.searchParams.set('state', state);
    window.location.href = redirectUrl.toString();
  });
});
