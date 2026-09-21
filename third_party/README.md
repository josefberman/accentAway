Seed-VC is cloned here by `backend/setup_seed_vc.sh`.

```
git clone --depth 1 https://github.com/Plachtaa/seed-vc.git third_party/seed-vc
```

The backend imports `real-time-gui.py` from this tree and loads `DiT_uvit_tat_xlsr` (tiny realtime). Set `SEED_VC_ROOT` to override the path. Without this clone the server still runs in **echo** mode for capture/playback testing.
