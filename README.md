# HackAlem AI · EKT product assistant

Minimal local prototype for the HackAlem AI Trade case. It uses the existing
`ekt_api_client.py` API client to search the EKT catalog by article or name,
request product details, and show stock and characteristics when those fields
are present in the API response. If no direct match exists, it suggests catalog
entries with overlapping name/article terms and clearly labels them as possible
alternatives.

## Run

Provide `EKT_API_BASE_URL`, `EKT_API_USERNAME`, and `EKT_API_PASSWORD` as
environment variables in the shell, then run:

```sh
python app.py
```

Open http://127.0.0.1:8000. The server binds to loopback only. The existing
`.env` is not read by the app or changed; credentials should be injected by the
local environment. `.env.example` documents the variable names.

The chat is catalog lookup only: it does not create orders, reserve goods, or
ask for payment or account credentials. It reports missing API fields as
unknown rather than inventing values. Search supports `/products`; product
details use `/products/detail?id=...`, matching the contracts in
`ekt_api_client.py`.
