# FreshMart POS

A modern point-of-sale system for FreshMart, built with React + Vite. Handles product browsing, cart management, VAT-aware checkout, and multiple payment methods.

---

## Project Structure

```
src/
├── api/
│   ├── config.js      # API URL, mock flag, WIRED payment flags, stub() helper
│   ├── client.js      # Low-level fetch() wrapper with auth + error handling
│   ├── index.js       # The only file the UI imports from — gateway to mock or real API
│   ├── mock.js        # Fake in-memory backend (no server needed)
│   └── mappers.js     # Normalises raw API responses into consistent shapes
├── components/
│   ├── CartPanel.jsx       # Right-side cart — slide-up drawer on mobile
│   ├── CheckoutModal.jsx   # Payment flow (Cash / M-Pesa / Card)
│   ├── ProductCard.jsx     # Individual product tile
│   └── Sidebar.jsx         # Desktop sidebar + mobile top/bottom nav
├── data/
│   └── products.js    # Seed product data with correct Kenya VAT rates
├── pages/
│   ├── Terminal.jsx   # Main cashier screen — stats, search, product grid
│   ├── NotFound.jsx   # 404 page
│   └── NotAuthorized.jsx  # 403 page (shown when payment method not wired)
├── config.js          # Store info (name, address, KRA PIN, phone, locale)
├── utils.js           # VAT constants, money formatter, cartTotals()
├── App.jsx            # Root — auth state, cart state, page routing
└── main.jsx           # Entry point — BrowserRouter + route definitions
```

---

## Getting Started

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The app runs on `http://localhost:5173` by default.

No backend needed — the mock API runs entirely in the browser.

---

## Environment Variables

Create a `.env` file in the root to configure:

```env
# Point to your real backend (default: http://localhost:5000/api)
VITE_API_URL=https://api.freshmart.co.ke/api

# Set to false to switch from mock to real backend
VITE_USE_MOCK=false
```

Without a `.env` file the app runs in mock mode automatically.

---

## Mock Mode (Default)

The mock API simulates a full backend in memory:

| Credential | Value |
|---|---|
| Email | `cashier@freshmart.co.ke` |
| Password | `demo1234` |

Data resets on page refresh. Stock levels update live as you make sales.

---

## VAT Rates (Kenya — Finance Act 2023)

| Rate | Applied to |
|---|---|
| 16% Standard | General goods (fruits, vegetables, drinks, household) |
| 0% Exempt | Basic food staples — bread, eggs, fresh milk |

VAT is calculated per line item based on each product's `vatRate` field.

---

## Payment Methods

| Method | Status | How to enable |
|---|---|---|
| Cash | ✅ Working | Always available |
| M-Pesa | ⏳ Not wired | Set `WIRED.mpesa = true` in `api/config.js` once Daraja is connected |
| Card | ⏳ Not wired | Set `WIRED.card = true` in `api/config.js` once gateway is connected |

Clicking an unwired payment method redirects to the 403 page.

---

## Collaboration

This project is split across teammates. Each person works on their own branch.

```bash
# Before starting work — get latest changes from main
git pull origin main

# Create your branch
git checkout -b your-name/feature-name

# Push your branch
git push -u origin your-name/feature-name
```

Then open a Pull Request on GitHub for review before merging to `main`.

### Modules by teammate

| Module | Branch | Status |
|---|---|---|
| POS Terminal + Cart + Checkout | `korir/pos-terminal` | ✅ Done |
| Login / Auth page | — | ⏳ Pending |
| M-Pesa Daraja integration | — | ⏳ Pending |
| Card payment gateway | — | ⏳ Pending |

---

## Tech Stack

- **React 19** — UI
- **Vite** — build tool
- **Tailwind CSS v4** — styling
- **Lucide React** — icons
- **Bootstrap Icons** — product icons
- **React Router v6** — routing (404, 403 pages)
