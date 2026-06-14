#!/usr/bin/env python3
"""
BACINI LARGHI per la selezione semestrale point-in-time.

Ogni settore operativo ha un bacino ampio di candidati (storicamente rappresentativi,
non solo i big di OGGI). Ogni 6 mesi (gennaio + luglio) il sistema calcola il
dollar-volume medio di ogni titolo sui mesi precedenti quella data e pesca i TOP_N
piu' liquidi -> quello diventa il paniere attivo per il semestre successivo.

Criterio: dollar-volume (prezzo x volume) = proxy onesto e point-in-time di
dimensione/liquidita'. Calcolato solo con dati fino alla data di revisione,
quindi NESSUN senno di poi.

Nota: i bacini includono di proposito anche titoli che in passato erano grandi
e oggi lo sono meno (e viceversa), cosi' la selezione storica e' realistica.
"""

# Numero di titoli da pescare dal bacino a ogni revisione
TOP_N = 15

# Revisione semestrale: gennaio e luglio
REVIEW_MONTHS = (1, 7)

# Finestra (in settimane) su cui calcolare il dollar-volume medio prima di ogni revisione
DV_LOOKBACK_WEEKS = 26  # ~6 mesi

# ---------------------------------------------------------------------------
# BACINI USA — ampi, storicamente rappresentativi
# ---------------------------------------------------------------------------
BASKETS = {
    # Tecnologia USA (large+mega cap software/hardware, inclusi nomi storici)
    'XLK': ['NVDA','MSFT','AAPL','AVGO','ORCL','CSCO','AMD','IBM','QCOM','TXN',
            'ACN','ADBE','CRM','INTC','NOW','INTU','AMAT','MU','HPQ','DELL',
            'WDAY','SNPS','CDNS','ANSS','FTNT','PANW','KEYS','GLW','HPE','NTAP',
            'ADSK','ROP','MSI','APH','TEL','CTSH','IT','WDC','STX','ZBRA',
            'JNPR','FFIV','AKAM','VRSN','SWKS','GEN','TYL','PTC','CDW','EPAM'],

    # Semiconduttori
    'SOXX': ['NVDA','TSM','AVGO','MU','AMD','ASML','AMAT','LRCX','KLAC','ADI',
             'INTC','QCOM','TXN','MRVL','MCHP','ON','SWKS','MPWR','QRVO','TER',
             'ENTG','LSCC','WOLF','AMKR','SLAB','FORM','POWI','SITM','RMBS','UCTT',
             'NXPI','STM','ARM','GFS','ALGM','SMCI','COHR','NVMI','ACLS','CRUS'],

    # Finanziari USA (banche, broker, assicurazioni, servizi finanziari)
    'XLF': ['JPM','BAC','WFC','GS','MS','BX','C','AXP','SPGI','BLK',
            'SCHW','CB','MMC','PGR','CME','ICE','AON','USB','PNC','TFC',
            'COF','MET','AIG','PRU','TRV','ALL','AFL','MTB','FITB','HBAN',
            'BK','STT','NTRS','KEY','RF','CFG','SYF','DFS','AMP','RJF',
            'MCO','MSCI','NDAQ','CINF','WRB','L','ACGL','HIG','PFG','GL'],

    # Sanità USA (pharma, biotech, devices, payers, services)
    'XLV': ['LLY','UNH','JNJ','ABBV','MRK','PFE','TMO','ABT','DHR','ISRG',
            'AMGN','GILD','CVS','MDT','BMY','VRTX','REGN','CI','ELV','HUM',
            'ZTS','BSX','SYK','BDX','HCA','MCK','CAH','COR','DXCM','IDXX',
            'BIIB','MRNA','RMD','EW','IQV','A','MTD','WST','HOLX','ZBH',
            'BAX','STE','PODD','ALGN','DGX','LH','CNC','MOH','VTRS','CTLT'],

    # Industriali USA (aerospace, machinery, transport, building)
    'XLI': ['GE','RTX','CAT','HON','UNP','BA','DE','ETN','LMT','UPS',
            'ADP','CSX','NOC','GD','EMR','ITW','MMM','FDX','NSC','WM',
            'PH','TT','CMI','ROP','PCAR','CARR','OTIS','PAYX','FAST','JCI',
            'CPRT','URI','GWW','RSG','AME','ODFL','VRSK','EFX','DOV','IR',
            'HWM','XYL','WAB','FTV','LHX','TDG','PWR','BR','TXT','SNA'],

    # Beni consumo difensivi (staples)
    'XLP': ['WMT','COST','PG','KO','PEP','PM','MDLZ','MO','CL','KMB',
            'GIS','SYY','KHC','STZ','HSY','KDP','KR','MKC','CHD','CLX',
            'K','HRL','CAG','SJM','CPB','TAP','TSN','BG','ADM','LW',
            'MNST','KVUE','DG','DLTR','TGT','EL','KMX','WBA','BF.B','CASY'],

    # Energia USA (oil&gas, services, midstream)
    'XLE': ['XOM','CVX','COP','EOG','SLB','MPC','PSX','OXY','VLO','KMI',
            'WMB','HES','DVN','HAL','BKR','FANG','OKE','TRGP','MRO','APA',
            'CTRA','EQT','LNG','OVV','RRC','AR','MTDR','CHRD','SM','PR',
            'XEC','PXD','CXO','NBL','MUR','HP','NOV','FTI','VNOM','DINO'],

    # Banche EU (Borsa Italiana, .MI)
    'EXV1.DE': ['ISP.MI','UCG.MI','BAMI.MI','BMPS.MI','MB.MI','BPSO.MI','BPER.MI','FBK.MI',
                'BGN.MI','UNI.MI','BMED.MI','BPE.MI','CE.MI','CASS.MI','ILTY.MI'],

    # Assicurazioni (Borsa Italiana, .MI)
    'EXH5.DE': ['G.MI','UNI.MI','PST.MI','CASS.MI','VAS.MI','NET.MI'],
}

# I 9 settori operativi del sistema (coerenti con SECTORS_SYSTEM)
OPERATIONAL_SECTORS = list(BASKETS.keys())

if __name__ == '__main__':
    print(f"Bacini definiti: {len(BASKETS)} settori")
    tot = 0
    for sec, tks in BASKETS.items():
        uniq = sorted(set(tks))
        if len(uniq) != len(tks):
            print(f"  ⚠ {sec}: {len(tks)-len(uniq)} duplicati")
        tot += len(uniq)
        print(f"  {sec:10} {len(uniq):3} titoli")
    print(f"\nTotale candidati (unici per settore): ~{tot}")
    print(f"TOP_N per revisione: {TOP_N} · revisione: mesi {REVIEW_MONTHS} · lookback {DV_LOOKBACK_WEEKS}w")
