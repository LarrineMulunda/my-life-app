"""
Ticker database — NSE, NYSE, NASDAQ, LSE, JSE stocks and ETFs.
Loaded once into the DB on startup. Searchable via /api/tickers endpoint.
"""

# ── Ticker data ───────────────────────────────────────────────────────────────
# Format: (symbol, name, exchange, type, currency, sector)

TICKER_DATA = [
    # ── NSE (Nairobi Securities Exchange) ─────────────────────────────────────
    ("SCOM",  "Safaricom PLC",                   "NSE","stock","KES","Telecommunications"),
    ("EQTY",  "Equity Group Holdings",           "NSE","stock","KES","Banking"),
    ("KCB",   "KCB Group PLC",                   "NSE","stock","KES","Banking"),
    ("COOP",  "Co-operative Bank of Kenya",      "NSE","stock","KES","Banking"),
    ("NCBA",  "NCBA Group PLC",                  "NSE","stock","KES","Banking"),
    ("ABSA",  "Absa Bank Kenya PLC",             "NSE","stock","KES","Banking"),
    ("SCBK",  "Standard Chartered Bank Kenya",   "NSE","stock","KES","Banking"),
    ("DTK",   "Diamond Trust Bank Kenya",        "NSE","stock","KES","Banking"),
    ("NMG",   "Nation Media Group",              "NSE","stock","KES","Media"),
    ("BAMB",  "Bamburi Cement PLC",              "NSE","stock","KES","Construction"),
    ("EABL",  "East African Breweries",          "NSE","stock","KES","Consumer"),
    ("BAT",   "British American Tobacco Kenya",  "NSE","stock","KES","Consumer"),
    ("KEGN",  "KenGen Company PLC",              "NSE","stock","KES","Energy"),
    ("KPLC",  "Kenya Power & Lighting Co",       "NSE","stock","KES","Energy"),
    ("KENR",  "Kenya Re-Insurance",              "NSE","stock","KES","Insurance"),
    ("CFC",   "CIC Insurance Group",             "NSE","stock","KES","Insurance"),
    ("JUB",   "Jubilee Holdings",                "NSE","stock","KES","Insurance"),
    ("BRIT",  "Britam Holdings",                 "NSE","stock","KES","Insurance"),
    ("ARM",   "ARM Cement PLC",                  "NSE","stock","KES","Construction"),
    ("CARB",  "Carbacid Investments",            "NSE","stock","KES","Industrial"),
    ("NSE",   "Nairobi Securities Exchange",     "NSE","stock","KES","Financial Services"),
    ("UMME",  "Umeme Limited",                   "NSE","stock","KES","Energy"),
    ("WTK",   "Williamson Tea Kenya",            "NSE","stock","KES","Agriculture"),
    ("KAPC",  "Kapchorua Tea Kenya",             "NSE","stock","KES","Agriculture"),
    ("LIMT",  "Limuru Tea PLC",                  "NSE","stock","KES","Agriculture"),
    ("TOTL",  "Total Energies EP Kenya",         "NSE","stock","KES","Energy"),
    ("CTUM",  "Centum Investment Company",       "NSE","stock","KES","Investment"),
    ("HFCK",  "HF Group PLC",                    "NSE","stock","KES","Financial Services"),
    ("FIRE",  "Nairobi Business Ventures",       "NSE","stock","KES","Retail"),
    ("SCAN",  "ScanGroup PLC",                   "NSE","stock","KES","Media"),
    ("TCL",   "TransCentury Limited",            "NSE","stock","KES","Infrastructure"),
    # NSE ETFs
    ("NSETF10","NSE Derivatives Market ETF",     "NSE","etf","KES","ETF"),

    # ── NYSE ──────────────────────────────────────────────────────────────────
    ("BRK.B", "Berkshire Hathaway Inc Class B",  "NYSE","stock","USD","Financials"),
    ("JPM",   "JPMorgan Chase & Co",             "NYSE","stock","USD","Banking"),
    ("BAC",   "Bank of America Corp",            "NYSE","stock","USD","Banking"),
    ("WMT",   "Walmart Inc",                     "NYSE","stock","USD","Consumer"),
    ("XOM",   "Exxon Mobil Corp",                "NYSE","stock","USD","Energy"),
    ("JNJ",   "Johnson & Johnson",               "NYSE","stock","USD","Healthcare"),
    ("PG",    "Procter & Gamble Co",             "NYSE","stock","USD","Consumer"),
    ("CVX",   "Chevron Corporation",             "NYSE","stock","USD","Energy"),
    ("MA",    "Mastercard Inc",                  "NYSE","stock","USD","Financials"),
    ("UNH",   "UnitedHealth Group",              "NYSE","stock","USD","Healthcare"),
    ("HD",    "Home Depot Inc",                  "NYSE","stock","USD","Retail"),
    ("KO",    "Coca-Cola Company",               "NYSE","stock","USD","Consumer"),
    ("DIS",   "Walt Disney Company",             "NYSE","stock","USD","Media"),
    ("VZ",    "Verizon Communications",          "NYSE","stock","USD","Telecommunications"),
    ("PFE",   "Pfizer Inc",                      "NYSE","stock","USD","Healthcare"),
    ("MRK",   "Merck & Co Inc",                  "NYSE","stock","USD","Healthcare"),
    ("ABT",   "Abbott Laboratories",             "NYSE","stock","USD","Healthcare"),
    ("NKE",   "Nike Inc",                        "NYSE","stock","USD","Consumer"),
    ("MCD",   "McDonald's Corporation",          "NYSE","stock","USD","Consumer"),
    ("IBM",   "International Business Machines", "NYSE","stock","USD","Technology"),
    # NYSE ETFs
    ("SPY",   "SPDR S&P 500 ETF Trust",          "NYSE","etf","USD","ETF - US Equity"),
    ("GLD",   "SPDR Gold Shares",                "NYSE","etf","USD","ETF - Commodities"),
    ("VTI",   "Vanguard Total Stock Market ETF", "NYSE","etf","USD","ETF - US Equity"),
    ("EFA",   "iShares MSCI EAFE ETF",           "NYSE","etf","USD","ETF - International"),
    ("EEM",   "iShares MSCI Emerging Markets",   "NYSE","etf","USD","ETF - Emerging Markets"),
    ("AGG",   "iShares Core US Aggregate Bond",  "NYSE","etf","USD","ETF - Bonds"),
    ("VNQ",   "Vanguard Real Estate ETF",        "NYSE","etf","USD","ETF - Real Estate"),
    ("IAU",   "iShares Gold Trust",              "NYSE","etf","USD","ETF - Commodities"),
    ("DIA",   "SPDR Dow Jones Industrial ETF",   "NYSE","etf","USD","ETF - US Equity"),
    ("XLK",   "Technology Select Sector SPDR",   "NYSE","etf","USD","ETF - Technology"),
    ("XLF",   "Financial Select Sector SPDR",    "NYSE","etf","USD","ETF - Financials"),
    ("VWO",   "Vanguard FTSE Emerging Markets",  "NYSE","etf","USD","ETF - Emerging Markets"),
    ("BND",   "Vanguard Total Bond Market ETF",  "NYSE","etf","USD","ETF - Bonds"),
    ("IVV",   "iShares Core S&P 500 ETF",        "NYSE","etf","USD","ETF - US Equity"),

    # ── NASDAQ ────────────────────────────────────────────────────────────────
    ("AAPL",  "Apple Inc",                       "NASDAQ","stock","USD","Technology"),
    ("MSFT",  "Microsoft Corporation",           "NASDAQ","stock","USD","Technology"),
    ("GOOGL", "Alphabet Inc Class A",            "NASDAQ","stock","USD","Technology"),
    ("AMZN",  "Amazon.com Inc",                  "NASDAQ","stock","USD","Technology"),
    ("NVDA",  "NVIDIA Corporation",              "NASDAQ","stock","USD","Technology"),
    ("META",  "Meta Platforms Inc",              "NASDAQ","stock","USD","Technology"),
    ("TSLA",  "Tesla Inc",                       "NASDAQ","stock","USD","Technology"),
    ("AVGO",  "Broadcom Inc",                    "NASDAQ","stock","USD","Technology"),
    ("COST",  "Costco Wholesale Corp",           "NASDAQ","stock","USD","Consumer"),
    ("NFLX",  "Netflix Inc",                     "NASDAQ","stock","USD","Technology"),
    ("INTC",  "Intel Corporation",               "NASDAQ","stock","USD","Technology"),
    ("AMD",   "Advanced Micro Devices",          "NASDAQ","stock","USD","Technology"),
    ("ADBE",  "Adobe Inc",                       "NASDAQ","stock","USD","Technology"),
    ("PYPL",  "PayPal Holdings Inc",             "NASDAQ","stock","USD","Fintech"),
    ("CSCO",  "Cisco Systems Inc",               "NASDAQ","stock","USD","Technology"),
    ("PEP",   "PepsiCo Inc",                     "NASDAQ","stock","USD","Consumer"),
    ("QCOM",  "QUALCOMM Incorporated",           "NASDAQ","stock","USD","Technology"),
    ("TXN",   "Texas Instruments Inc",           "NASDAQ","stock","USD","Technology"),
    ("SBUX",  "Starbucks Corporation",           "NASDAQ","stock","USD","Consumer"),
    ("GILD",  "Gilead Sciences Inc",             "NASDAQ","stock","USD","Healthcare"),
    # NASDAQ ETFs
    ("QQQ",   "Invesco QQQ Trust (Nasdaq-100)",  "NASDAQ","etf","USD","ETF - Technology"),
    ("TQQQ",  "ProShares UltraPro QQQ 3x",       "NASDAQ","etf","USD","ETF - Leveraged"),
    ("SQQQ",  "ProShares UltraPro Short QQQ",    "NASDAQ","etf","USD","ETF - Inverse"),
    ("VGT",   "Vanguard Information Technology", "NASDAQ","etf","USD","ETF - Technology"),
    ("ARKK",  "ARK Innovation ETF",              "NASDAQ","etf","USD","ETF - Innovation"),

    # ── LSE (London Stock Exchange) ───────────────────────────────────────────
    ("SHEL",  "Shell PLC",                       "LSE","stock","GBP","Energy"),
    ("AZN",   "AstraZeneca PLC",                 "LSE","stock","GBP","Healthcare"),
    ("HSBA",  "HSBC Holdings PLC",               "LSE","stock","GBP","Banking"),
    ("BP",    "BP PLC",                          "LSE","stock","GBP","Energy"),
    ("ULVR",  "Unilever PLC",                    "LSE","stock","GBP","Consumer"),
    ("GSK",   "GSK PLC",                         "LSE","stock","GBP","Healthcare"),
    ("LLOY",  "Lloyds Banking Group",            "LSE","stock","GBP","Banking"),
    ("BARC",  "Barclays PLC",                    "LSE","stock","GBP","Banking"),
    ("VOD",   "Vodafone Group PLC",              "LSE","stock","GBP","Telecommunications"),
    ("RIO",   "Rio Tinto PLC",                   "LSE","stock","GBP","Mining"),
    ("AAL",   "Anglo American PLC",              "LSE","stock","GBP","Mining"),
    ("BT.A",  "BT Group PLC",                    "LSE","stock","GBP","Telecommunications"),
    ("PRU",   "Prudential PLC",                  "LSE","stock","GBP","Insurance"),
    # LSE ETFs
    ("ISF",   "iShares Core FTSE 100 UCITS ETF", "LSE","etf","GBP","ETF - UK Equity"),
    ("VWRL",  "Vanguard FTSE All-World UCITS ETF","LSE","etf","USD","ETF - Global"),
    ("CSPX",  "iShares Core S&P 500 UCITS ETF",  "LSE","etf","USD","ETF - US Equity"),
    ("SWDA",  "iShares Core MSCI World UCITS ETF","LSE","etf","USD","ETF - Global"),

    # ── JSE (Johannesburg Stock Exchange) ─────────────────────────────────────
    ("NPN",   "Naspers Limited",                 "JSE","stock","ZAR","Technology"),
    ("PRX",   "Prosus NV",                       "JSE","stock","ZAR","Technology"),
    ("SBK",   "Standard Bank Group",             "JSE","stock","ZAR","Banking"),
    ("FSR",   "Firstrand Limited",               "JSE","stock","ZAR","Banking"),
    ("ABG",   "Absa Group Limited",              "JSE","stock","ZAR","Banking"),
    ("NED",   "Nedbank Group Limited",           "JSE","stock","ZAR","Banking"),
    ("MTN",   "MTN Group Limited",               "JSE","stock","ZAR","Telecommunications"),
    ("VOD.JO","Vodacom Group",                   "JSE","stock","ZAR","Telecommunications"),
    ("SOL",   "Sasol Limited",                   "JSE","stock","ZAR","Energy"),
    ("ANG",   "AngloGold Ashanti",               "JSE","stock","ZAR","Mining"),
    ("GFI",   "Gold Fields Limited",             "JSE","stock","ZAR","Mining"),
    ("IMP",   "Impala Platinum Holdings",        "JSE","stock","ZAR","Mining"),

    # ── EURONEXT ──────────────────────────────────────────────────────────────
    ("ASML",  "ASML Holding NV",                 "EURONEXT","stock","EUR","Technology"),
    ("MC",    "LVMH Moët Hennessy",             "EURONEXT","stock","EUR","Consumer Luxury"),
    ("OR",    "L'Oréal SA",                      "EURONEXT","stock","EUR","Consumer"),
    ("SAN",   "Sanofi SA",                       "EURONEXT","stock","EUR","Healthcare"),
    ("AIR",   "Airbus SE",                       "EURONEXT","stock","EUR","Aerospace"),
    ("BNP",   "BNP Paribas SA",                  "EURONEXT","stock","EUR","Banking"),
    ("TTE",   "TotalEnergies SE",                "EURONEXT","stock","EUR","Energy"),

    # ── HKEX ──────────────────────────────────────────────────────────────────
    ("700",   "Tencent Holdings",                "HKEX","stock","HKD","Technology"),
    ("9988",  "Alibaba Group Holding",           "HKEX","stock","HKD","Technology"),
    ("3690",  "Meituan",                         "HKEX","stock","HKD","Technology"),
    ("9618",  "JD.com Inc",                      "HKEX","stock","HKD","E-Commerce"),
    ("1",     "CKH Holdings",                    "HKEX","stock","HKD","Conglomerate"),
    ("941",   "China Mobile Limited",            "HKEX","stock","HKD","Telecommunications"),
]


def seed_tickers(conn):
    """Insert default tickers — skip on conflict (symbol, exchange)."""
    from db import ph, is_pg
    p = ph()
    cur = conn.cursor()
    for row in TICKER_DATA:
        try:
            if is_pg():
                cur.execute("""
                    INSERT INTO tickers (symbol,name,exchange,type,currency,sector)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(symbol,exchange) DO NOTHING
                """, row)
            else:
                cur.execute("""
                    INSERT OR IGNORE INTO tickers
                        (symbol,name,exchange,type,currency,sector)
                    VALUES (?,?,?,?,?,?)
                """, row)
        except Exception:
            pass
    conn.commit()
