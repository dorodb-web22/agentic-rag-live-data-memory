# Frontend

The Basic Agent Query UI uses React, TypeScript, and Vite. It sends `POST /query` with `{ "query": "..." }` and expects `{ "answer": "..." }`.

## Local development

Run the FastAPI server at `http://localhost:8000`, then in this directory run:

```sh
npm install
npm run dev
```

Vite serves the UI at `http://localhost:5173` and proxies `/query` to `http://localhost:8000`, avoiding a browser cross-origin request in development. Set `VITE_API_ORIGIN` in a local `.env` file to use a different backend origin; `.env.example` shows the default. Do not put secrets in frontend environment variables.

The backend needs to implement `POST /query` and return an `answer` string. If calling the API directly from another frontend origin, allow `http://localhost:5173` in backend CORS settings. With the included Vite proxy, browser requests are same-origin and backend CORS is not required for local development.

## Build

```sh
npm run build
```
