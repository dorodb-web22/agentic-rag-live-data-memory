# Landing page

Single static file: `index.html` (no build step, no npm).

Run locally:  `cd landing && python3 -m http.server 5500`  then open http://localhost:5500

## Google sign-in setup
1. Google Cloud Console > APIs & Services > Credentials > Create OAuth client ID > Web application.
2. Authorized JavaScript origins: `http://localhost:5500` (add your real domain later).
3. Paste the client ID into `GOOGLE_CLIENT_ID` at the top of the script in `index.html`.
4. Backend: set `GOOGLE_CLIENT_ID` and `SESSION_SECRET`, add `backend/auth_google.py` router, allow CORS for the landing origin with credentials (see the docstring in that file).
5. Set `APP_URL` in `index.html` to wherever the React app runs.
