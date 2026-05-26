"""
Comprehensive ticker database — 300+ instruments across 8 exchanges.
NSE, NYSE, NASDAQ, LSE, JSE, EURONEXT, HKEX + African exchanges.
Stocks, ETFs, REITs, Index Funds.
"""

# (symbol, name, exchange, type, currency, sector)
TICKER_DATA = [

  # ════════════════════════════════════════════════════════════
  # NSE — Nairobi Securities Exchange
  # ════════════════════════════════════════════════════════════
  # Banking
  ("EQTY","Equity Group Holdings","NSE","stock","KES","Banking"),
  ("KCB","KCB Group PLC","NSE","stock","KES","Banking"),
  ("COOP","Co-operative Bank of Kenya","NSE","stock","KES","Banking"),
  ("NCBA","NCBA Group PLC","NSE","stock","KES","Banking"),
  ("ABSA","Absa Bank Kenya PLC","NSE","stock","KES","Banking"),
  ("SCBK","Standard Chartered Bank Kenya","NSE","stock","KES","Banking"),
  ("DTK","Diamond Trust Bank Kenya","NSE","stock","KES","Banking"),
  ("HF","HF Group PLC","NSE","stock","KES","Financial Services"),
  ("I&M","I&M Group PLC","NSE","stock","KES","Banking"),
  ("NBK","National Bank of Kenya","NSE","stock","KES","Banking"),
  ("STBK","Stanbic Bank Kenya","NSE","stock","KES","Banking"),
  # Telecoms
  ("SCOM","Safaricom PLC","NSE","stock","KES","Telecommunications"),
  # Insurance
  ("JUB","Jubilee Holdings","NSE","stock","KES","Insurance"),
  ("BRIT","Britam Holdings","NSE","stock","KES","Insurance"),
  ("CFC","CIC Insurance Group","NSE","stock","KES","Insurance"),
  ("KENR","Kenya Re-Insurance","NSE","stock","KES","Insurance"),
  ("LIMT","Liberty Holdings Kenya","NSE","stock","KES","Insurance"),
  # Energy & Utilities
  ("KEGN","KenGen Company PLC","NSE","stock","KES","Energy"),
  ("KPLC","Kenya Power & Lighting Co","NSE","stock","KES","Utilities"),
  ("TOTL","Total Energies EP Kenya","NSE","stock","KES","Energy"),
  ("UMME","Umeme Limited","NSE","stock","KES","Energy"),
  # Consumer & Retail
  ("EABL","East African Breweries","NSE","stock","KES","Consumer"),
  ("BAT","British American Tobacco Kenya","NSE","stock","KES","Consumer"),
  ("NMG","Nation Media Group","NSE","stock","KES","Media"),
  ("SGL","Standard Group Limited","NSE","stock","KES","Media"),
  ("SCAN","ScanGroup PLC","NSE","stock","KES","Media"),
  ("UNGA","Unga Group PLC","NSE","stock","KES","Food & Beverage"),
  ("SASN","Sasini PLC","NSE","stock","KES","Agriculture"),
  ("KAPC","Kapchorua Tea Kenya","NSE","stock","KES","Agriculture"),
  ("LIMT2","Limuru Tea PLC","NSE","stock","KES","Agriculture"),
  ("WTK","Williamson Tea Kenya","NSE","stock","KES","Agriculture"),
  ("FTGH","Flame Tree Group Holdings","NSE","stock","KES","Consumer"),
  # Investment & Finance
  ("CTUM","Centum Investment Company","NSE","stock","KES","Investment"),
  ("NSE","Nairobi Securities Exchange","NSE","stock","KES","Financial Services"),
  ("XPRS","Express Kenya PLC","NSE","stock","KES","Logistics"),
  # Industrial & Construction
  ("BAMB","Bamburi Cement PLC","NSE","stock","KES","Construction"),
  ("ARM","ARM Cement PLC","NSE","stock","KES","Construction"),
  ("CARB","Carbacid Investments","NSE","stock","KES","Industrial"),
  ("BOC","BOC Kenya PLC","NSE","stock","KES","Industrial"),
  ("BERG","Berger Paints Kenya","NSE","stock","KES","Industrial"),
  ("CABL","East African Cables","NSE","stock","KES","Industrial"),
  ("EVRD","Eveready East Africa","NSE","stock","KES","Consumer"),
  ("TCL","TransCentury Limited","NSE","stock","KES","Infrastructure"),
  # Real Estate
  ("KURV","Kurwitu Ventures","NSE","stock","KES","Real Estate"),
  ("HAFR","Home Africa Limited","NSE","stock","KES","Real Estate"),
  # REITs
  ("ILAM","ILAM Fahari I-REIT","NSE","reit","KES","Real Estate"),
  ("ACORN","Acorn Student Accommodation D-REIT","NSE","reit","KES","Real Estate"),
  # NSE ETFs / Funds
  ("CMMF","CIC Money Market Fund","NSE","etf","KES","Money Market"),
  ("STANLIB","Stanlib Money Market Fund","NSE","etf","KES","Money Market"),

  # ════════════════════════════════════════════════════════════
  # NYSE — New York Stock Exchange
  # ════════════════════════════════════════════════════════════
  # Blue chips
  ("BRK.B","Berkshire Hathaway Inc Class B","NYSE","stock","USD","Financials"),
  ("JPM","JPMorgan Chase & Co","NYSE","stock","USD","Banking"),
  ("BAC","Bank of America Corp","NYSE","stock","USD","Banking"),
  ("C","Citigroup Inc","NYSE","stock","USD","Banking"),
  ("WFC","Wells Fargo & Company","NYSE","stock","USD","Banking"),
  ("GS","Goldman Sachs Group","NYSE","stock","USD","Banking"),
  ("MS","Morgan Stanley","NYSE","stock","USD","Banking"),
  ("WMT","Walmart Inc","NYSE","stock","USD","Retail"),
  ("XOM","Exxon Mobil Corp","NYSE","stock","USD","Energy"),
  ("CVX","Chevron Corporation","NYSE","stock","USD","Energy"),
  ("JNJ","Johnson & Johnson","NYSE","stock","USD","Healthcare"),
  ("PG","Procter & Gamble Co","NYSE","stock","USD","Consumer"),
  ("MA","Mastercard Inc","NYSE","stock","USD","Fintech"),
  ("V","Visa Inc","NYSE","stock","USD","Fintech"),
  ("UNH","UnitedHealth Group","NYSE","stock","USD","Healthcare"),
  ("HD","Home Depot Inc","NYSE","stock","USD","Retail"),
  ("KO","Coca-Cola Company","NYSE","stock","USD","Consumer"),
  ("DIS","Walt Disney Company","NYSE","stock","USD","Media"),
  ("VZ","Verizon Communications","NYSE","stock","USD","Telecommunications"),
  ("PFE","Pfizer Inc","NYSE","stock","USD","Healthcare"),
  ("MRK","Merck & Co Inc","NYSE","stock","USD","Healthcare"),
  ("ABT","Abbott Laboratories","NYSE","stock","USD","Healthcare"),
  ("NKE","Nike Inc","NYSE","stock","USD","Consumer"),
  ("MCD","McDonald's Corporation","NYSE","stock","USD","Consumer"),
  ("IBM","International Business Machines","NYSE","stock","USD","Technology"),
  ("T","AT&T Inc","NYSE","stock","USD","Telecommunications"),
  ("CRM","Salesforce Inc","NYSE","stock","USD","Technology"),
  ("BA","Boeing Company","NYSE","stock","USD","Aerospace"),
  ("GE","General Electric Company","NYSE","stock","USD","Industrial"),
  ("CAT","Caterpillar Inc","NYSE","stock","USD","Industrial"),
  ("MMM","3M Company","NYSE","stock","USD","Industrial"),
  ("AXP","American Express Company","NYSE","stock","USD","Financials"),
  ("WBA","Walgreens Boots Alliance","NYSE","stock","USD","Healthcare"),
  ("LLY","Eli Lilly and Company","NYSE","stock","USD","Healthcare"),
  ("PM","Philip Morris International","NYSE","stock","USD","Consumer"),
  # NYSE ETFs
  ("SPY","SPDR S&P 500 ETF Trust","NYSE","etf","USD","ETF - US Large Cap"),
  ("GLD","SPDR Gold Shares","NYSE","etf","USD","ETF - Commodities"),
  ("VTI","Vanguard Total Stock Market ETF","NYSE","etf","USD","ETF - US Total Market"),
  ("EFA","iShares MSCI EAFE ETF","NYSE","etf","USD","ETF - International Developed"),
  ("EEM","iShares MSCI Emerging Markets ETF","NYSE","etf","USD","ETF - Emerging Markets"),
  ("AGG","iShares Core US Aggregate Bond ETF","NYSE","etf","USD","ETF - US Bonds"),
  ("VNQ","Vanguard Real Estate ETF","NYSE","etf","USD","ETF - Real Estate"),
  ("IAU","iShares Gold Trust","NYSE","etf","USD","ETF - Commodities"),
  ("DIA","SPDR Dow Jones Industrial ETF","NYSE","etf","USD","ETF - US Large Cap"),
  ("XLK","Technology Select Sector SPDR ETF","NYSE","etf","USD","ETF - Technology"),
  ("XLF","Financial Select Sector SPDR ETF","NYSE","etf","USD","ETF - Financials"),
  ("XLE","Energy Select Sector SPDR ETF","NYSE","etf","USD","ETF - Energy"),
  ("XLV","Health Care Select Sector SPDR ETF","NYSE","etf","USD","ETF - Healthcare"),
  ("XLI","Industrial Select Sector SPDR ETF","NYSE","etf","USD","ETF - Industrials"),
  ("VWO","Vanguard FTSE Emerging Markets ETF","NYSE","etf","USD","ETF - Emerging Markets"),
  ("BND","Vanguard Total Bond Market ETF","NYSE","etf","USD","ETF - US Bonds"),
  ("IVV","iShares Core S&P 500 ETF","NYSE","etf","USD","ETF - US Large Cap"),
  ("VEA","Vanguard FTSE Developed Markets ETF","NYSE","etf","USD","ETF - International"),
  ("SLV","iShares Silver Trust","NYSE","etf","USD","ETF - Commodities"),
  ("TLT","iShares 20+ Year Treasury Bond ETF","NYSE","etf","USD","ETF - US Treasury"),
  ("HYG","iShares iBoxx High Yield Corp Bond","NYSE","etf","USD","ETF - High Yield Bonds"),
  ("LQD","iShares iBoxx Investment Grade Bond","NYSE","etf","USD","ETF - Corp Bonds"),
  ("VIG","Vanguard Dividend Appreciation ETF","NYSE","etf","USD","ETF - Dividend"),
  ("DVY","iShares Select Dividend ETF","NYSE","etf","USD","ETF - Dividend"),
  ("IWM","iShares Russell 2000 ETF","NYSE","etf","USD","ETF - US Small Cap"),
  ("MDY","SPDR S&P MidCap 400 ETF","NYSE","etf","USD","ETF - US Mid Cap"),
  ("ACWI","iShares MSCI ACWI ETF","NYSE","etf","USD","ETF - Global"),
  ("IEMG","iShares Core MSCI Emerging Markets","NYSE","etf","USD","ETF - Emerging Markets"),
  ("VGK","Vanguard FTSE Europe ETF","NYSE","etf","USD","ETF - Europe"),
  ("EWJ","iShares MSCI Japan ETF","NYSE","etf","USD","ETF - Japan"),
  ("FXI","iShares China Large-Cap ETF","NYSE","etf","USD","ETF - China"),
  ("GDX","VanEck Gold Miners ETF","NYSE","etf","USD","ETF - Gold Miners"),
  ("USO","United States Oil Fund","NYSE","etf","USD","ETF - Oil"),

  # ════════════════════════════════════════════════════════════
  # NASDAQ
  # ════════════════════════════════════════════════════════════
  ("AAPL","Apple Inc","NASDAQ","stock","USD","Technology"),
  ("MSFT","Microsoft Corporation","NASDAQ","stock","USD","Technology"),
  ("GOOGL","Alphabet Inc Class A","NASDAQ","stock","USD","Technology"),
  ("GOOG","Alphabet Inc Class C","NASDAQ","stock","USD","Technology"),
  ("AMZN","Amazon.com Inc","NASDAQ","stock","USD","E-Commerce"),
  ("NVDA","NVIDIA Corporation","NASDAQ","stock","USD","Semiconductors"),
  ("META","Meta Platforms Inc","NASDAQ","stock","USD","Social Media"),
  ("TSLA","Tesla Inc","NASDAQ","stock","USD","Electric Vehicles"),
  ("AVGO","Broadcom Inc","NASDAQ","stock","USD","Semiconductors"),
  ("COST","Costco Wholesale Corp","NASDAQ","stock","USD","Retail"),
  ("NFLX","Netflix Inc","NASDAQ","stock","USD","Streaming"),
  ("INTC","Intel Corporation","NASDAQ","stock","USD","Semiconductors"),
  ("AMD","Advanced Micro Devices","NASDAQ","stock","USD","Semiconductors"),
  ("ADBE","Adobe Inc","NASDAQ","stock","USD","Software"),
  ("PYPL","PayPal Holdings Inc","NASDAQ","stock","USD","Fintech"),
  ("CSCO","Cisco Systems Inc","NASDAQ","stock","USD","Networking"),
  ("PEP","PepsiCo Inc","NASDAQ","stock","USD","Consumer"),
  ("QCOM","QUALCOMM Incorporated","NASDAQ","stock","USD","Semiconductors"),
  ("TXN","Texas Instruments Inc","NASDAQ","stock","USD","Semiconductors"),
  ("SBUX","Starbucks Corporation","NASDAQ","stock","USD","Consumer"),
  ("GILD","Gilead Sciences Inc","NASDAQ","stock","USD","Healthcare"),
  ("AMGN","Amgen Inc","NASDAQ","stock","USD","Biotechnology"),
  ("ISRG","Intuitive Surgical Inc","NASDAQ","stock","USD","Medical Devices"),
  ("REGN","Regeneron Pharmaceuticals","NASDAQ","stock","USD","Biotechnology"),
  ("MRNA","Moderna Inc","NASDAQ","stock","USD","Biotechnology"),
  ("ABNB","Airbnb Inc","NASDAQ","stock","USD","Travel"),
  ("UBER","Uber Technologies Inc","NASDAQ","stock","USD","Mobility"),
  ("LYFT","Lyft Inc","NASDAQ","stock","USD","Mobility"),
  ("SNAP","Snap Inc","NASDAQ","stock","USD","Social Media"),
  ("TWTR","Twitter / X Corp","NASDAQ","stock","USD","Social Media"),
  ("HOOD","Robinhood Markets Inc","NASDAQ","stock","USD","Fintech"),
  ("COIN","Coinbase Global Inc","NASDAQ","stock","USD","Crypto Exchange"),
  ("SQ","Block Inc","NASDAQ","stock","USD","Fintech"),
  ("SHOP","Shopify Inc","NASDAQ","stock","USD","E-Commerce"),
  ("ZM","Zoom Video Communications","NASDAQ","stock","USD","Software"),
  ("DOCU","DocuSign Inc","NASDAQ","stock","USD","Software"),
  ("OKTA","Okta Inc","NASDAQ","stock","USD","Cybersecurity"),
  ("CRWD","CrowdStrike Holdings","NASDAQ","stock","USD","Cybersecurity"),
  ("PANW","Palo Alto Networks","NASDAQ","stock","USD","Cybersecurity"),
  ("NET","Cloudflare Inc","NASDAQ","stock","USD","Cloud Infrastructure"),
  ("SNOW","Snowflake Inc","NASDAQ","stock","USD","Cloud Data"),
  ("DDOG","Datadog Inc","NASDAQ","stock","USD","Cloud Monitoring"),
  ("MDB","MongoDB Inc","NASDAQ","stock","USD","Database"),
  ("PLTR","Palantir Technologies","NASDAQ","stock","USD","AI/Data Analytics"),
  ("AI","C3.ai Inc","NASDAQ","stock","USD","AI/Data Analytics"),
  # NASDAQ ETFs
  ("QQQ","Invesco QQQ Trust (Nasdaq-100)","NASDAQ","etf","USD","ETF - Tech/Growth"),
  ("TQQQ","ProShares UltraPro QQQ 3x Bull","NASDAQ","etf","USD","ETF - Leveraged"),
  ("SQQQ","ProShares UltraPro Short QQQ","NASDAQ","etf","USD","ETF - Inverse"),
  ("VGT","Vanguard Information Technology ETF","NASDAQ","etf","USD","ETF - Technology"),
  ("ARKK","ARK Innovation ETF","NASDAQ","etf","USD","ETF - Disruptive Innovation"),
  ("ARKW","ARK Next Generation Internet ETF","NASDAQ","etf","USD","ETF - Internet"),
  ("ARKG","ARK Genomic Revolution ETF","NASDAQ","etf","USD","ETF - Genomics"),
  ("SOXX","iShares Semiconductor ETF","NASDAQ","etf","USD","ETF - Semiconductors"),
  ("HACK","ETFMG Prime Cyber Security ETF","NASDAQ","etf","USD","ETF - Cybersecurity"),
  ("BOTZ","Global X Robotics & AI ETF","NASDAQ","etf","USD","ETF - Robotics/AI"),
  ("SKYY","First Trust Cloud Computing ETF","NASDAQ","etf","USD","ETF - Cloud"),
  ("ROBO","ROBO Global Robotics ETF","NASDAQ","etf","USD","ETF - Robotics"),
  ("AIQ","Global X AI & Technology ETF","NASDAQ","etf","USD","ETF - AI"),
  ("WCLD","WisdomTree Cloud Computing ETF","NASDAQ","etf","USD","ETF - Cloud"),

  # ════════════════════════════════════════════════════════════
  # LSE — London Stock Exchange
  # ════════════════════════════════════════════════════════════
  ("SHEL","Shell PLC","LSE","stock","GBP","Energy"),
  ("AZN","AstraZeneca PLC","LSE","stock","GBP","Healthcare"),
  ("HSBA","HSBC Holdings PLC","LSE","stock","GBP","Banking"),
  ("BP","BP PLC","LSE","stock","GBP","Energy"),
  ("ULVR","Unilever PLC","LSE","stock","GBP","Consumer"),
  ("GSK","GSK PLC","LSE","stock","GBP","Healthcare"),
  ("LLOY","Lloyds Banking Group","LSE","stock","GBP","Banking"),
  ("BARC","Barclays PLC","LSE","stock","GBP","Banking"),
  ("NWG","NatWest Group PLC","LSE","stock","GBP","Banking"),
  ("VOD","Vodafone Group PLC","LSE","stock","GBP","Telecommunications"),
  ("RIO","Rio Tinto PLC","LSE","stock","GBP","Mining"),
  ("AAL","Anglo American PLC","LSE","stock","GBP","Mining"),
  ("BT.A","BT Group PLC","LSE","stock","GBP","Telecommunications"),
  ("PRU","Prudential PLC","LSE","stock","GBP","Insurance"),
  ("STAN","Standard Chartered PLC","LSE","stock","GBP","Banking"),
  ("EXPN","Experian PLC","LSE","stock","GBP","Data Analytics"),
  ("REL","RELX PLC","LSE","stock","GBP","Information Services"),
  ("CPG","Compass Group PLC","LSE","stock","GBP","Food Services"),
  ("DGE","Diageo PLC","LSE","stock","GBP","Consumer"),
  ("BATS","British American Tobacco PLC","LSE","stock","GBP","Consumer"),
  ("IMB","Imperial Brands PLC","LSE","stock","GBP","Consumer"),
  ("WPP","WPP PLC","LSE","stock","GBP","Advertising"),
  ("SGE","Sage Group PLC","LSE","stock","GBP","Software"),
  ("AUTO","Auto Trader Group PLC","LSE","stock","GBP","Digital Marketplace"),
  ("WISE","Wise PLC","LSE","stock","GBP","Fintech"),
  ("MONZO","Monzo Bank (Private)","LSE","stock","GBP","Banking"),
  # LSE ETFs
  ("ISF","iShares Core FTSE 100 UCITS ETF","LSE","etf","GBP","ETF - UK Large Cap"),
  ("VWRL","Vanguard FTSE All-World UCITS ETF","LSE","etf","USD","ETF - Global"),
  ("CSPX","iShares Core S&P 500 UCITS ETF","LSE","etf","USD","ETF - US Large Cap"),
  ("SWDA","iShares Core MSCI World UCITS ETF","LSE","etf","USD","ETF - Global Developed"),
  ("EIMI","iShares Core MSCI EM IMI UCITS ETF","LSE","etf","USD","ETF - Emerging Markets"),
  ("IGLT","iShares Core UK Gilts UCITS ETF","LSE","etf","GBP","ETF - UK Bonds"),
  ("VUSA","Vanguard S&P 500 UCITS ETF","LSE","etf","USD","ETF - US Large Cap"),
  ("VFEM","Vanguard FTSE Emerging Markets ETF","LSE","etf","USD","ETF - Emerging Markets"),
  ("VMID","Vanguard FTSE 250 UCITS ETF","LSE","etf","GBP","ETF - UK Mid Cap"),
  ("VAGP","Vanguard Global Aggregate Bond ETF","LSE","etf","USD","ETF - Global Bonds"),
  ("INRG","iShares Global Clean Energy ETF","LSE","etf","USD","ETF - Clean Energy"),
  ("JREG","JPM Global Research Enh. Eq. ETF","LSE","etf","USD","ETF - Global Equity"),

  # ════════════════════════════════════════════════════════════
  # JSE — Johannesburg Stock Exchange
  # ════════════════════════════════════════════════════════════
  ("NPN","Naspers Limited","JSE","stock","ZAR","Technology"),
  ("PRX","Prosus NV","JSE","stock","ZAR","Technology"),
  ("SBK","Standard Bank Group","JSE","stock","ZAR","Banking"),
  ("FSR","Firstrand Limited","JSE","stock","ZAR","Banking"),
  ("ABG","Absa Group Limited","JSE","stock","ZAR","Banking"),
  ("NED","Nedbank Group Limited","JSE","stock","ZAR","Banking"),
  ("CPI","Capitec Bank Holdings","JSE","stock","ZAR","Banking"),
  ("MTN","MTN Group Limited","JSE","stock","ZAR","Telecommunications"),
  ("VOD.JO","Vodacom Group","JSE","stock","ZAR","Telecommunications"),
  ("SOL","Sasol Limited","JSE","stock","ZAR","Energy"),
  ("ANG","AngloGold Ashanti","JSE","stock","ZAR","Mining"),
  ("GFI","Gold Fields Limited","JSE","stock","ZAR","Mining"),
  ("IMP","Impala Platinum Holdings","JSE","stock","ZAR","Mining"),
  ("AMS","Anglo American Platinum","JSE","stock","ZAR","Mining"),
  ("SHP","Shoprite Holdings","JSE","stock","ZAR","Retail"),
  ("WHL","Woolworths Holdings","JSE","stock","ZAR","Retail"),
  ("TFG","The Foschini Group","JSE","stock","ZAR","Retail"),
  ("MRP","Mr Price Group","JSE","stock","ZAR","Retail"),
  ("DSY","Discovery Limited","JSE","stock","ZAR","Insurance"),
  ("SLM","Sanlam Limited","JSE","stock","ZAR","Insurance"),
  ("RMH","RMB Holdings","JSE","stock","ZAR","Financials"),
  # JSE ETFs
  ("STXNDF","Satrix NASDAQ 100 ETF","JSE","etf","ZAR","ETF - US Tech"),
  ("STXSPY","Satrix S&P 500 ETF","JSE","etf","ZAR","ETF - US Large Cap"),
  ("STXWDM","Satrix MSCI World ETF","JSE","etf","ZAR","ETF - Global"),
  ("NFEMF","Newfunds EMIF ETF","JSE","etf","ZAR","ETF - Emerging Markets"),

  # ════════════════════════════════════════════════════════════
  # EURONEXT
  # ════════════════════════════════════════════════════════════
  ("ASML","ASML Holding NV","EURONEXT","stock","EUR","Semiconductors"),
  ("MC","LVMH Moët Hennessy Louis Vuitton","EURONEXT","stock","EUR","Luxury Goods"),
  ("OR","L'Oréal SA","EURONEXT","stock","EUR","Consumer"),
  ("SAN","Sanofi SA","EURONEXT","stock","EUR","Healthcare"),
  ("AIR","Airbus SE","EURONEXT","stock","EUR","Aerospace"),
  ("BNP","BNP Paribas SA","EURONEXT","stock","EUR","Banking"),
  ("TTE","TotalEnergies SE","EURONEXT","stock","EUR","Energy"),
  ("SU","Schneider Electric SE","EURONEXT","stock","EUR","Industrial"),
  ("SAP","SAP SE","EURONEXT","stock","EUR","Software"),
  ("DBK","Deutsche Bank AG","EURONEXT","stock","EUR","Banking"),
  ("BMW","BMW AG","EURONEXT","stock","EUR","Automotive"),
  ("VOW","Volkswagen AG","EURONEXT","stock","EUR","Automotive"),
  ("ADS","Adidas AG","EURONEXT","stock","EUR","Consumer"),
  ("DPW","Deutsche Post AG","EURONEXT","stock","EUR","Logistics"),
  ("ALV","Allianz SE","EURONEXT","stock","EUR","Insurance"),
  ("MUV2","Munich Re Group","EURONEXT","stock","EUR","Insurance"),
  ("INGA","ING Groep NV","EURONEXT","stock","EUR","Banking"),
  ("PHIA","Philips NV","EURONEXT","stock","EUR","Healthcare"),
  ("HEIA","Heineken NV","EURONEXT","stock","EUR","Consumer"),
  ("AD","Koninklijke Ahold Delhaize","EURONEXT","stock","EUR","Retail"),
  # EURONEXT ETFs
  ("PANX","Lyxor Pan Africa ETF","EURONEXT","etf","USD","ETF - Africa"),
  ("PAEEM","Amundi MSCI EM ESG Leaders ETF","EURONEXT","etf","USD","ETF - Emerging Markets"),
  ("CW8","Amundi MSCI World UCITS ETF","EURONEXT","etf","EUR","ETF - Global"),

  # ════════════════════════════════════════════════════════════
  # HKEX — Hong Kong Exchange
  # ════════════════════════════════════════════════════════════
  ("700","Tencent Holdings Limited","HKEX","stock","HKD","Technology"),
  ("9988","Alibaba Group Holding Limited","HKEX","stock","HKD","E-Commerce"),
  ("3690","Meituan","HKEX","stock","HKD","Tech Platform"),
  ("9618","JD.com Inc","HKEX","stock","HKD","E-Commerce"),
  ("9999","NetEase Inc","HKEX","stock","HKD","Gaming"),
  ("1","CKH Holdings Limited","HKEX","stock","HKD","Conglomerate"),
  ("941","China Mobile Limited","HKEX","stock","HKD","Telecommunications"),
  ("939","China Construction Bank","HKEX","stock","HKD","Banking"),
  ("1398","ICBC","HKEX","stock","HKD","Banking"),
  ("3988","Bank of China Limited","HKEX","stock","HKD","Banking"),
  ("2318","Ping An Insurance Group","HKEX","stock","HKD","Insurance"),
  ("2382","Sunny Optical Technology","HKEX","stock","HKD","Technology"),
  ("1810","Xiaomi Corporation","HKEX","stock","HKD","Technology"),
  ("9888","Baidu Inc","HKEX","stock","HKD","Technology"),
  ("2269","WuXi Biologics","HKEX","stock","HKD","Biotechnology"),
  # HKEX ETFs
  ("2800","Tracker Fund of Hong Kong","HKEX","etf","HKD","ETF - HK Large Cap"),
  ("3067","iShares Hang Seng Tech ETF","HKEX","etf","HKD","ETF - HK Tech"),

  # ════════════════════════════════════════════════════════════
  # African Markets (DSE, USE, GSE, BRVM)
  # ════════════════════════════════════════════════════════════
  # DSE — Dar es Salaam Stock Exchange (Tanzania)
  ("CRDB","CRDB Bank PLC","DSE","stock","TZS","Banking"),
  ("NMB","NMB Bank PLC","DSE","stock","TZS","Banking"),
  ("TPCC","Tanzania Portland Cement","DSE","stock","TZS","Construction"),
  ("TOL","TOL Gas Limited","DSE","stock","TZS","Energy"),
  ("TBL","Tanzania Breweries Limited","DSE","stock","TZS","Consumer"),
  # USE — Uganda Securities Exchange
  ("UMEME.UG","Umeme Limited Uganda","USE","stock","UGX","Energy"),
  ("SBU","Stanbic Bank Uganda","USE","stock","UGX","Banking"),
  ("BOA","Bank of Africa Uganda","USE","stock","UGX","Banking"),
  # GSE — Ghana Stock Exchange
  ("GCB","GCB Bank Limited","GSE","stock","GHS","Banking"),
  ("CAL","CAL Bank Limited","GSE","stock","GHS","Banking"),
  ("MTNGH","MTN Ghana","GSE","stock","GHS","Telecommunications"),
  ("BOPP","Benso Oil Palm Plantation","GSE","stock","GHS","Agriculture"),
  # BRVM — West African Exchange
  ("SNTS","Sonatel Senegal","BRVM","stock","XOF","Telecommunications"),
  ("BICC","Bici Côte d'Ivoire","BRVM","stock","XOF","Banking"),
  ("ONTBV","Orange Côte d'Ivoire","BRVM","stock","XOF","Telecommunications"),

  # ════════════════════════════════════════════════════════════
  # Crypto (tracked like stocks for portfolio)
  # ════════════════════════════════════════════════════════════
  ("BTC","Bitcoin","CRYPTO","crypto","USD","Cryptocurrency"),
  ("ETH","Ethereum","CRYPTO","crypto","USD","Cryptocurrency"),
  ("BNB","Binance Coin","CRYPTO","crypto","USD","Cryptocurrency"),
  ("SOL","Solana","CRYPTO","crypto","USD","Cryptocurrency"),
  ("ADA","Cardano","CRYPTO","crypto","USD","Cryptocurrency"),
  ("XRP","Ripple / XRP","CRYPTO","crypto","USD","Cryptocurrency"),
  ("DOGE","Dogecoin","CRYPTO","crypto","USD","Cryptocurrency"),
  ("MATIC","Polygon","CRYPTO","crypto","USD","Cryptocurrency"),
  ("LINK","Chainlink","CRYPTO","crypto","USD","Cryptocurrency"),
  ("DOT","Polkadot","CRYPTO","crypto","USD","Cryptocurrency"),
]

CURRENCIES = ["KES","USD","GBP","EUR","ZAR","TZS","UGX","GHS","XOF","HKD","NGN","ZMW","Other"]

def seed_tickers(conn):
    from db import ph, is_pg
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
