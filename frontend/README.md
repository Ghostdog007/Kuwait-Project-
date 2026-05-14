# Frontend

Static map UI for deployment (Vercel-ready).

Files in `public/`:
- `trip_map.html`
- `map_app.js`
- `map_styles.css`
- `map_data.json` (generated)
- `map_config.js` (generated)

Serve locally from repo root:

```powershell
python -m http.server 8090 --directory frontend/public
```

Open: `http://localhost:8090/trip_map.html`
