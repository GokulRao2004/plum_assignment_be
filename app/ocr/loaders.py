from pathlib import Path
import zipfile
import pandas as pd

SAFE_TTYS = {'IN','PIN','MIN','SCD','SBD','SCDC','SCDF','SBDC'}
_rx_df = None
_diag_df = None
_lab_df = None


def read_rxnconso_from_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        name = [n for n in zf.namelist() if n.upper().endswith('RXNCONSO.RRF')][0]
        with zf.open(name) as f:
            return pd.read_csv(f, sep='|', header=None, dtype=str, encoding='utf-8', engine='python')


def read_rxnconso_from_dir(folder):
    file_path = list(Path(folder).rglob('RXNCONSO.RRF'))[0]
    return pd.read_csv(file_path, sep='|', header=None, dtype=str, encoding='utf-8', engine='python')


def load_vocab_csv(path):
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=['canonical', 'code', 'alias', 'alias_norm'])
    df = pd.read_csv(p, dtype=str).fillna('')
    df['alias_norm'] = df['alias'].str.lower().str.replace(r'[^a-z0-9]+', ' ', regex=True).str.strip()
    return df


def warm_vocabs(config):
    global _rx_df, _diag_df, _lab_df
    if _rx_df is not None:
        return _rx_df, _diag_df, _lab_df

    rxnorm_zip = config.get('RXNORM_ZIP') if isinstance(config, dict) else getattr(config, 'RXNORM_ZIP')
    rxnorm_dir = config.get('RXNORM_DIR') if isinstance(config, dict) else getattr(config, 'RXNORM_DIR')
    diagnosis_csv = config.get('DIAGNOSIS_CSV') if isinstance(config, dict) else getattr(config, 'DIAGNOSIS_CSV')
    labtest_csv = config.get('LABTEST_CSV') if isinstance(config, dict) else getattr(config, 'LABTEST_CSV')

    rx_df = read_rxnconso_from_zip(rxnorm_zip) if Path(rxnorm_zip).exists() else read_rxnconso_from_dir(rxnorm_dir)
    rx_df = rx_df.iloc[:, :18].copy()
    rx_df.columns = ['RXCUI','LAT','TS','LUI','STT','SUI','ISPREF','RXAUI','SAUI','SCUI','SDUI','SAB','TTY','CODE','STR','SRL','SUPPRESS','CVF']
    rx_df = rx_df[(rx_df['LAT'] == 'ENG') & (rx_df['STR'].notna()) & (rx_df['SAB'] == 'RXNORM') & (rx_df['TTY'].isin(SAFE_TTYS))]
    rx_df['STR_NORM'] = rx_df['STR'].str.lower().str.replace(r'[^a-z0-9]+', ' ', regex=True).str.strip()
    rx_df = rx_df[rx_df['STR_NORM'].str.len() >= 4].drop_duplicates(subset=['RXCUI', 'STR_NORM']).reset_index(drop=True)

    _rx_df = rx_df
    _diag_df = load_vocab_csv(diagnosis_csv)
    _lab_df = load_vocab_csv(labtest_csv)
    return _rx_df, _diag_df, _lab_df


def get_vocabs():
    if _rx_df is None:
        raise RuntimeError('Vocab not warmed. Call warm_vocabs(config) during app startup.')
    return _rx_df, _diag_df, _lab_df
