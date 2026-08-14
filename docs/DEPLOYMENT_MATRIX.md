# Deployment matrix

| Mode | Data | Integrations | Intended use | Support claim |
| --- | --- | --- | --- | --- |
| Local evaluation | Synthetic | Mocked or disabled | Inspect code and complete the walkthrough | Community documentation only |
| Public sandbox | Synthetic, resettable; anonymous short-lived sessions | Live MLC, DDEX, payment, partner delivery, and model services disabled | Inspect the workflow and verify receipts | Best-effort alpha availability |
| Adopter-owned staging | Operator-controlled | Optional, operator-authorized | Design-partner testing with controlled data | Explicit pilot agreement only |
| Adopter-owned production | Operator-controlled | Operator credentials and bilateral arrangements | Organization's governed permission desk | Not qualified by the alpha |
| Future Clef-hosted service | Undecided | Undecided | Consider only after demonstrated demand and sponsorship | Not offered |

Docker Compose is the portable evaluation path. Railway instructions describe a provisional customer-owned topology, not a verified one-click template. Operators own domains, secrets, databases, backups, email delivery, connector accounts, counterparties, and legal obligations.
