document.addEventListener('DOMContentLoaded', () => {
  const urlParams = new URLSearchParams(window.location.search);
  const setupToken = urlParams.get('setup');
  
  if (setupToken) {
    document.getElementById('login-section').style.display = 'none';
    document.getElementById('setup-section').style.display = 'block';
  }

  // Base64Url to Uint8Array helper
  function b64u2buf(b64u) {
    const b64 = b64u.replace(/-/g, '+').replace(/_/g, '/');
    const binStr = window.atob(b64 + '='.repeat((4 - b64.length % 4) % 4));
    const buf = new Uint8Array(binStr.length);
    for(let i=0; i<binStr.length; i++) buf[i] = binStr.charCodeAt(i);
    return buf.buffer;
  }
  
  // buf to Base64Url
  function buf2b64u(buf) {
    const binStr = String.fromCharCode(...new Uint8Array(buf));
    return window.btoa(binStr).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  }

  document.getElementById('login-btn').addEventListener('click', async () => {
    const errEl = document.getElementById('login-error');
    errEl.textContent = '';
    
    try {
      const optRes = await fetch('/api.cgi/api/auth/passkey/login/options', { method: 'POST' });
      const options = await optRes.json();
      
      if (options.error) throw new Error(options.error);

      // Convert options for navigator.credentials
      options.challenge = b64u2buf(options.challenge);
      if (options.allowCredentials) {
        options.allowCredentials.forEach(c => {
          c.id = b64u2buf(c.id);
        });
      }

      const assertion = await navigator.credentials.get({ publicKey: options });
      
      const response = {
        id: assertion.id,
        rawId: buf2b64u(assertion.rawId),
        type: assertion.type,
        response: {
          authenticatorData: buf2b64u(assertion.response.authenticatorData),
          clientDataJSON: buf2b64u(assertion.response.clientDataJSON),
          signature: buf2b64u(assertion.response.signature),
          userHandle: assertion.response.userHandle ? buf2b64u(assertion.response.userHandle) : null,
        }
      };

      const verRes = await fetch('/api.cgi/api/auth/passkey/login/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(response)
      });
      const result = await verRes.json();
      if (result.success) {
        const redirectUrl = new URLSearchParams(window.location.search).get('redirect');
        if (redirectUrl) {
          window.location.href = redirectUrl;
        } else {
          // Fallback if not coming from consent flow
          alert('Login successful! You can close this page.');
        }
      } else {
        throw new Error(result.error || 'Login failed');
      }
    } catch (e) {
      errEl.textContent = e.message;
    }
  });

  document.getElementById('setup-btn')?.addEventListener('click', async () => {
    const errEl = document.getElementById('setup-error');
    errEl.textContent = '';
    
    try {
      const optRes = await fetch('/api.cgi/api/auth/passkey/register/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ setup_token: setupToken })
      });
      const options = await optRes.json();
      
      if (options.error) throw new Error(options.error);

      options.challenge = b64u2buf(options.challenge);
      options.user.id = b64u2buf(options.user.id);
      if (options.excludeCredentials) {
        options.excludeCredentials.forEach(c => { c.id = b64u2buf(c.id); });
      }

      const attestation = await navigator.credentials.create({ publicKey: options });

      const response = {
        id: attestation.id,
        rawId: buf2b64u(attestation.rawId),
        type: attestation.type,
        response: {
          clientDataJSON: buf2b64u(attestation.response.clientDataJSON),
          attestationObject: buf2b64u(attestation.response.attestationObject),
        }
      };

      const verRes = await fetch('/api.cgi/api/auth/passkey/register/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(response)
      });
      const result = await verRes.json();
      
      if (result.success) {
        alert('Passkey registered successfully! You can now log in.');
        window.location.href = 'index.html';
      } else {
        throw new Error(result.error || 'Registration failed');
      }
    } catch (e) {
      errEl.textContent = e.message;
    }
  });
});
