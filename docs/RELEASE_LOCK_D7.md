# Release Lock (D7)

Ta dokument je "zadnja vrata" pred produkcijskim deployem in po deployu.

## 1) Pre-deploy (must pass)

1. `STRICT_ENV_CHECK=true ./scripts/final_gate_d7.sh`
2. `git status` mora biti čist (brez necommitanih sprememb, razen lokalnih logov)
3. `git rev-parse --short HEAD` zapiši v release notes
4. Ustvari release tag:
   - `git tag -a v1.0.0-d7 -m "D1-D7 stabilization release"`
   - `git push origin v1.0.0-d7`

## 2) Deploy

1. Push na `main` (če še ni)
2. Railway deploy iz `main`
3. Počakaj, da build in health check postaneta zeleno

## 3) Post-deploy sanity (must pass)

Zaženi:

```bash
BASE_URL="https://<railway-domain>" ADMIN_TOKEN="<admin-token>" ./scripts/postdeploy_sanity.sh
```

Script preveri:
- `/health`
- admin seznam rezervacij
- 3 chat tokove: booking, interrupt/info, splošni info

## 4) 60-minutno opazovanje

Vsakih 10 min preveri:
- `/health`
- admin create/confirm/reject
- 1 real booking tok v UI
- error log spike (5xx / timeout)

## 5) Rollback plan (če gre karkoli narobe)

1. Najdi zadnji stabilni commit:
   - `git log --oneline -n 15`
2. Re-deploy na zadnji stabilni tag/commit (v Railway izberi prejšnji release)
3. Če moraš lokalno popraviti in redeployati:
   - `git checkout <stable-tag-or-commit>`
   - `git checkout -b hotfix/rollback-<date>`
   - push branch + deploy branch snapshot
4. Komunikacija:
   - zapiši incident čas, vpliv, root cause, corrective action

## 6) Minimalni release zapis

- `release_version`: npr. `v1.0.0-d7`
- `git_commit`: npr. `08aeda2`
- `deployed_at`: UTC timestamp
- `validated_by`: ime
- `sanity_result`: pass/fail
