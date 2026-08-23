# Omni AI

A permission-first AI workspace concept. The interface is a dependency-free static prototype that can be opened on any device.

## Run locally

```bash
python3 -m http.server 4173 --bind 0.0.0.0
```

Then open `http://localhost:4173`.

The current prototype includes:

- A calm, responsive workspace dashboard
- A permission gate before a request can create a plan
- Recent activity and automation status
- Local models, web search, and Omni router provider cards
- Mobile-friendly layout with no build step or paid dependency

The UI intentionally treats permissions as a first-class product feature: a future backend should enforce the same approval boundary server-side before executing tools, browsing, sending messages, modifying files, or spending money.
