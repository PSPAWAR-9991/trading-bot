"""
Smart Money Concepts Trading Bot - Cloud Version
Optimized for Render.com free tier
"""

import os
import sys

# Install dependencies on first run
def install_packages():
    packages = [
        'kiteconnect',
        'python-telegram-bot',
        'pandas',
        'numpy',
        'requests',
        'schedule',
        'pytz'
    ]
    for package in packages:
        os.system(f'{sys.executable} -m pip install {package} --quiet')

try:
    import kiteconnect
except ImportError:
    print("Installing dependencies...")
    install_packages()

from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import requests
from telegram import Bot
import asyncio
import schedule
import pytz

# ==================== CONFIGURATION ====================
KITE_API_KEY = os.getenv("KITE_API_KEY", "y5sjs8ll7573yljk")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "jfg2h1awygthew82s69zxda000fiqu48")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8652868686:AAGZMfW1I2Bv7ayFuGL7pdJMOpHgHK8jf-0")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "487569268")

TRADING_SYMBOLS = ["NIFTY 50", "NIFTY BANK"]
SCAN_INTERVAL_MINUTES = 5
MIN_CONFIDENCE_SCORE = 70
MAX_TRADES_PER_DAY = 5

IST = pytz.timezone('Asia/Kolkata')

print("="*70)
print("🤖 SMART MONEY CONCEPTS - OPTIONS TRADING BOT")
print("="*70)
print(f"📅 Started: {datetime.now(IST).strftime('%d-%m-%Y %H:%M:%S IST')}")
print("="*70)

# ==================== KITE CONNECTION ====================
class KiteAPI:
    def __init__(self):
        self.kite = KiteConnect(api_key=KITE_API_KEY)
        self.access_token = None
        self.login_url = None
        
    def get_login_url(self):
        """Generate login URL for manual token generation"""
        self.login_url = self.kite.login_url()
        return self.login_url
    
    def set_access_token(self, access_token):
        """Set pre-generated access token"""
        self.access_token = access_token
        self.kite.set_access_token(access_token)
        return True
    
    def generate_session(self, request_token):
        """Generate session from request token"""
        try:
            data = self.kite.generate_session(request_token, api_secret=KITE_API_SECRET)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)
            print(f"✅ Kite Connected: {data.get('user_name', 'User')}")
            print(f"📍 Access Token: {self.access_token[:30]}...")
            return self.access_token
        except Exception as e:
            print(f"❌ Session Error: {e}")
            return None
    
    def get_ltp(self, symbol):
        """Get Last Traded Price"""
        try:
            key = f"NSE:{symbol}"
            quote = self.kite.quote(key)
            return quote[key]['last_price']
        except Exception as e:
            print(f"⚠️  LTP Error for {symbol}: {e}")
            return None
    
    def get_historical(self, symbol, days=3):
        """Fetch historical candle data"""
        try:
            instruments = self.kite.instruments("NSE")
            instrument = [i for i in instruments if i['tradingsymbol'] == symbol]
            
            if not instrument:
                return pd.DataFrame()
            
            token = instrument[0]['instrument_token']
            from_date = datetime.now() - timedelta(days=days)
            to_date = datetime.now()
            
            data = self.kite.historical_data(
                token, 
                from_date, 
                to_date, 
                "5minute"
            )
            
            df = pd.DataFrame(data)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df
            
        except Exception as e:
            print(f"⚠️  Historical data error for {symbol}: {e}")
            return pd.DataFrame()

# ==================== NSE OPTION CHAIN ====================
class NSEData:
    BASE_URL = "https://www.nseindia.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
        })
        # Initialize session
        try:
            self.session.get(self.BASE_URL, timeout=10)
        except:
            pass
    
    def get_option_chain(self, symbol):
        """Fetch option chain from NSE"""
        try:
            clean_symbol = symbol.replace(" ", "").replace("50", "").replace("BANK", "BANK")
            url = f"{self.BASE_URL}/api/option-chain-indices?symbol={clean_symbol}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"⚠️  Option chain error: {e}")
        
        return {}
    
    def parse_option_chain(self, data):
        """Parse option chain data"""
        if 'records' not in data or 'data' not in data['records']:
            return pd.DataFrame()
        
        records = data['records']['data']
        parsed = []
        
        for record in records:
            strike = record.get('strikePrice', 0)
            
            if 'CE' in record:
                ce = record['CE']
                parsed.append({
                    'strike': strike,
                    'type': 'CE',
                    'oi': ce.get('openInterest', 0),
                    'oi_change': ce.get('changeinOpenInterest', 0),
                    'ltp': ce.get('lastPrice', 0),
                    'volume': ce.get('totalTradedVolume', 0),
                    'iv': ce.get('impliedVolatility', 0),
                })
            
            if 'PE' in record:
                pe = record['PE']
                parsed.append({
                    'strike': strike,
                    'type': 'PE',
                    'oi': pe.get('openInterest', 0),
                    'oi_change': pe.get('changeinOpenInterest', 0),
                    'ltp': pe.get('lastPrice', 0),
                    'volume': pe.get('totalTradedVolume', 0),
                    'iv': pe.get('impliedVolatility', 0),
                })
        
        return pd.DataFrame(parsed)

# ==================== SMART MONEY CONCEPTS ====================
class SMCAnalyzer:
    def __init__(self, df):
        self.df = df
    
    def add_indicators(self):
        """Add technical indicators"""
        if self.df.empty or len(self.df) < 21:
            return self.df
        
        # EMAs
        self.df['ema9'] = self.df['close'].ewm(span=9, adjust=False).mean()
        self.df['ema21'] = self.df['close'].ewm(span=21, adjust=False).mean()
        
        # VWAP
        typical_price = (self.df['high'] + self.df['low'] + self.df['close']) / 3
        self.df['vwap'] = (typical_price * self.df['volume']).cumsum() / self.df['volume'].cumsum()
        
        # RSI
        delta = self.df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.df['rsi'] = 100 - (100 / (1 + rs))
        
        return self.df
    
    def identify_order_blocks(self):
        """Identify Order Blocks"""
        obs = []
        
        for i in range(2, len(self.df)):
            # Bullish OB: Last bearish before strong bullish
            if (self.df['close'].iloc[i] > self.df['open'].iloc[i] and
                self.df['close'].iloc[i-1] < self.df['open'].iloc[i-1] and
                self.df['close'].iloc[i] > self.df['high'].iloc[i-2]):
                
                obs.append({
                    'type': 'bullish',
                    'price': self.df['low'].iloc[i-1],
                    'index': i-1,
                    'strength': 10
                })
            
            # Bearish OB: Last bullish before strong bearish
            elif (self.df['close'].iloc[i] < self.df['open'].iloc[i] and
                  self.df['close'].iloc[i-1] > self.df['open'].iloc[i-1] and
                  self.df['close'].iloc[i] < self.df['low'].iloc[i-2]):
                
                obs.append({
                    'type': 'bearish',
                    'price': self.df['high'].iloc[i-1],
                    'index': i-1,
                    'strength': 10
                })
        
        return obs[-5:] if obs else []
    
    def identify_fvg(self):
        """Fair Value Gaps"""
        fvgs = []
        
        for i in range(2, len(self.df)):
            # Bullish FVG
            if self.df['low'].iloc[i] > self.df['high'].iloc[i-2]:
                gap_size = ((self.df['low'].iloc[i] - self.df['high'].iloc[i-2]) / 
                           self.df['high'].iloc[i-2] * 100)
                if gap_size > 0.2:  # Minimum 0.2% gap
                    fvgs.append({
                        'type': 'bullish',
                        'gap': gap_size,
                        'strength': 8
                    })
            
            # Bearish FVG
            elif self.df['high'].iloc[i] < self.df['low'].iloc[i-2]:
                gap_size = ((self.df['low'].iloc[i-2] - self.df['high'].iloc[i]) / 
                           self.df['low'].iloc[i-2] * 100)
                if gap_size > 0.2:
                    fvgs.append({
                        'type': 'bearish',
                        'gap': gap_size,
                        'strength': 8
                    })
        
        return fvgs[-3:] if fvgs else []
    
    def identify_bos_choch(self):
        """Break of Structure / Change of Character"""
        if len(self.df) < 10:
            return []
        
        # Simple trend detection based on swing highs/lows
        recent_highs = self.df['high'].tail(10).max()
        recent_lows = self.df['low'].tail(10).min()
        current_high = self.df['high'].iloc[-1]
        current_low = self.df['low'].iloc[-1]
        
        structures = []
        
        # Bullish BOS
        if current_high > recent_highs:
            structures.append({
                'type': 'BOS',
                'direction': 'bullish',
                'strength': 12
            })
        
        # Bearish BOS
        if current_low < recent_lows:
            structures.append({
                'type': 'BOS',
                'direction': 'bearish',
                'strength': 12
            })
        
        return structures
    
    def get_trend(self):
        """Determine current trend"""
        if len(self.df) < 21:
            return 'neutral'
        
        last = self.df.iloc[-1]
        
        if last['close'] > last['ema9'] > last['ema21']:
            return 'bullish'
        elif last['close'] < last['ema9'] < last['ema21']:
            return 'bearish'
        else:
            return 'neutral'

# ==================== SIGNAL GENERATOR ====================
class SignalGenerator:
    def __init__(self, kite, nse):
        self.kite = kite
        self.nse = nse
        self.daily_signals = 0
        self.last_reset = datetime.now(IST).date()
    
    def reset_daily_counter(self):
        """Reset daily signal counter"""
        today = datetime.now(IST).date()
        if today > self.last_reset:
            self.daily_signals = 0
            self.last_reset = today
            print(f"\n📅 New trading day: {today}")
    
    def analyze(self, symbol):
        """Analyze symbol and generate signal"""
        print(f"\n📊 Analyzing {symbol}...")
        
        # Check daily limit
        self.reset_daily_counter()
        if self.daily_signals >= MAX_TRADES_PER_DAY:
            print(f"   ⚠️  Max daily signals reached ({MAX_TRADES_PER_DAY})")
            return None
        
        # Get spot price
        spot_price = self.kite.get_ltp(symbol)
        if not spot_price:
            print(f"   ❌ Could not fetch spot price")
            return None
        
        print(f"   💰 Spot: ₹{spot_price:.2f}")
        
        # Get historical data
        df = self.kite.get_historical(symbol)
        if df.empty or len(df) < 20:
            print(f"   ❌ Insufficient historical data")
            return None
        
        # SMC Analysis
        smc = SMCAnalyzer(df)
        smc.add_indicators()
        
        obs = smc.identify_order_blocks()
        fvgs = smc.identify_fvg()
        structures = smc.identify_bos_choch()
        trend = smc.get_trend()
        
        print(f"   📈 Trend: {trend.upper()}")
        print(f"   🔷 Order Blocks: {len(obs)}")
        print(f"   ⚡ FVGs: {len(fvgs)}")
        
        # Get option chain
        nse_symbol = "NIFTY" if "50" in symbol else "BANKNIFTY"
        oc_data = self.nse.get_option_chain(nse_symbol)
        oc_df = self.nse.parse_option_chain(oc_data)
        
        # Option analysis
        pcr = 0
        ce_oi_change = pe_oi_change = 0
        
        if not oc_df.empty:
            ce_oi = oc_df[oc_df['type'] == 'CE']['oi'].sum()
            pe_oi = oc_df[oc_df['type'] == 'PE']['oi'].sum()
            pcr = pe_oi / ce_oi if ce_oi > 0 else 1
            
            ce_oi_change = oc_df[oc_df['type'] == 'CE']['oi_change'].sum()
            pe_oi_change = oc_df[oc_df['type'] == 'PE']['oi_change'].sum()
            
            print(f"   📊 PCR: {pcr:.2f}")
            print(f"   📈 CE OI Change: {ce_oi_change:,.0f}")
            print(f"   📉 PE OI Change: {pe_oi_change:,.0f}")
        
        # Generate signal
        signal = self.generate_signal(
            symbol, spot_price, trend, obs, fvgs, structures,
            pcr, ce_oi_change, pe_oi_change, df.iloc[-1]
        )
        
        if signal:
            self.daily_signals += 1
        
        return signal
    
    def generate_signal(self, symbol, price, trend, obs, fvgs, structures, 
                       pcr, ce_change, pe_change, latest_candle):
        """Generate trading signal with confidence score"""
        
        bull_score = 0
        bull_reasons = []
        
        bear_score = 0
        bear_reasons = []
        
        # === BULLISH ANALYSIS (BUY CE) ===
        
        # Trend
        if trend == 'bullish':
            bull_score += 15
            bull_reasons.append("Bullish trend (EMA)")
        
        # Order Blocks
        if obs and obs[-1]['type'] == 'bullish':
            bull_score += 20
            bull_reasons.append("Bullish Order Block detected")
        
        # Fair Value Gap
        if fvgs and fvgs[-1]['type'] == 'bullish':
            bull_score += 15
            bull_reasons.append(f"Bullish FVG ({fvgs[-1]['gap']:.2f}%)")
        
        # Structure Break
        if structures:
            for s in structures:
                if s['direction'] == 'bullish':
                    bull_score += s['strength']
                    bull_reasons.append(f"Bullish {s['type']}")
        
        # Option OI
        if pe_change < 0:
            bull_score += 12
            bull_reasons.append("Put unwinding")
        
        if ce_change > 0:
            bull_score += 8
            bull_reasons.append("Call buildup")
        
        # PCR
        if pcr < 0.7:
            bull_score += 12
            bull_reasons.append(f"Bullish PCR ({pcr:.2f})")
        
        # Price above VWAP
        if 'vwap' in latest_candle and latest_candle['close'] > latest_candle['vwap']:
            bull_score += 8
            bull_reasons.append("Above VWAP")
        
        # RSI
        if 'rsi' in latest_candle and 40 <= latest_candle['rsi'] <= 65:
            bull_score += 5
            bull_reasons.append(f"RSI favorable ({latest_candle['rsi']:.1f})")
        
        # === BEARISH ANALYSIS (BUY PE) ===
        
        # Trend
        if trend == 'bearish':
            bear_score += 15
            bear_reasons.append("Bearish trend (EMA)")
        
        # Order Blocks
        if obs and obs[-1]['type'] == 'bearish':
            bear_score += 20
            bear_reasons.append("Bearish Order Block detected")
        
        # Fair Value Gap
        if fvgs and fvgs[-1]['type'] == 'bearish':
            bear_score += 15
            bear_reasons.append(f"Bearish FVG ({fvgs[-1]['gap']:.2f}%)")
        
        # Structure Break
        if structures:
            for s in structures:
                if s['direction'] == 'bearish':
                    bear_score += s['strength']
                    bear_reasons.append(f"Bearish {s['type']}")
        
        # Option OI
        if ce_change < 0:
            bear_score += 12
            bear_reasons.append("Call unwinding")
        
        if pe_change > 0:
            bear_score += 8
            bear_reasons.append("Put buildup")
        
        # PCR
        if pcr > 1.3:
            bear_score += 12
            bear_reasons.append(f"Bearish PCR ({pcr:.2f})")
        
        # Price below VWAP
        if 'vwap' in latest_candle and latest_candle['close'] < latest_candle['vwap']:
            bear_score += 8
            bear_reasons.append("Below VWAP")
        
        # RSI
        if 'rsi' in latest_candle and 35 <= latest_candle['rsi'] <= 60:
            bear_score += 5
            bear_reasons.append(f"RSI favorable ({latest_candle['rsi']:.1f})")
        
        # === DETERMINE SIGNAL ===
        
        direction = None
        confidence = 0
        reasons = []
        
        if bull_score >= MIN_CONFIDENCE_SCORE and bull_score > bear_score:
            direction = "BUY CE"
            confidence = min(bull_score, 100)
            reasons = bull_reasons
        elif bear_score >= MIN_CONFIDENCE_SCORE and bear_score > bull_score:
            direction = "BUY PE"
            confidence = min(bear_score, 100)
            reasons = bear_reasons
        
        if not direction:
            print(f"   ⚠️  No signal (Bull: {bull_score}, Bear: {bear_score})")
            return None
        
        # Calculate strike and targets
        atm_strike = round(price / 100) * 100
        
        # Estimate premium (simplified - in real scenario, fetch actual premium)
        estimated_premium = 150
        
        signal = {
            'symbol': symbol,
            'direction': direction,
            'strike': atm_strike,
            'spot_price': price,
            'entry': estimated_premium,
            'sl': round(estimated_premium * 0.82),  # 18% SL
            't1': round(estimated_premium * 1.25),  # 25% gain
            't2': round(estimated_premium * 1.40),  # 40% gain
            't3': round(estimated_premium * 1.60),  # 60% gain
            'confidence': confidence,
            'reasons': ' + '.join(reasons[:4]),  # Top 4 reasons
            'timestamp': datetime.now(IST).strftime('%H:%M:%S')
        }
        
        return signal

# ==================== TELEGRAM NOTIFIER ====================
class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.chat_id = TELEGRAM_CHAT_ID
    
    async def send_signal(self, signal):
        """Send trading signal to Telegram"""
        emoji = "🟢" if "CE" in signal['direction'] else "🔴"
        
        message = f"""
{emoji} <b>TRADING SIGNAL</b> {emoji}

<b>Symbol:</b> {signal['symbol']}
<b>Direction:</b> {signal['direction']}
<b>Strike:</b> {signal['strike']}
<b>Spot Price:</b> ₹{signal['spot_price']:.2f}

💰 <b>Entry:</b> ₹{signal['entry']}
🛑 <b>Stop Loss:</b> ₹{signal['sl']}

🎯 <b>Targets:</b>
   T1: ₹{signal['t1']} (+{((signal['t1']/signal['entry']-1)*100):.0f}%)
   T2: ₹{signal['t2']} (+{((signal['t2']/signal['entry']-1)*100):.0f}%)
   T3: ₹{signal['t3']} (+{((signal['t3']/signal['entry']-1)*100):.0f}%)

📊 <b>Confidence:</b> {signal['confidence']}%
💡 <b>Reason:</b> {signal['reasons']}

⏰ <b>Time:</b> {signal['timestamp']} IST
"""
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            print(f"   ✅ Signal sent to Telegram!")
            return True
        except Exception as e:
            print(f"   ❌ Telegram error: {e}")
            return False
    
    async def send_message(self, text):
        """Send custom message"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

# ==================== MAIN BOT ====================
class TradingBot:
    def __init__(self):
        self.kite = KiteAPI()
        self.nse = NSEData()
        self.telegram = TelegramNotifier()
        self.signal_gen = None
        self.is_running = False
        
        # Generate login URL
        login_url = self.kite.get_login_url()
        print(f"\n🔐 Kite Login Required:")
        print(f"📍 Visit: {login_url}")
        print(f"\n⚠️  After login, you'll get a URL with 'request_token'")
        print(f"⚠️  Set that as REQUEST_TOKEN environment variable and restart\n")
        
        # Try to use request token from environment
        request_token = os.getenv("REQUEST_TOKEN")
        
        if request_token:
            access_token = self.kite.generate_session(request_token)
            if access_token:
                self.signal_gen = SignalGenerator(self.kite, self.nse)
                self.send_startup_message()
                self.is_running = True
            else:
                print("❌ Failed to generate session. Check REQUEST_TOKEN")
        else:
            # Try using pre-set access token
            access_token = os.getenv("ACCESS_TOKEN")
            if access_token:
                self.kite.set_access_token(access_token)
                self.signal_gen = SignalGenerator(self.kite, self.nse)
                self.send_startup_message()
                self.is_running = True
                print("✅ Using existing ACCESS_TOKEN")
    
    def send_startup_message(self):
        """Send bot startup notification"""
        try:
            message = """
🤖 <b>Trading Bot Started!</b>

📊 <b>Monitoring:</b> NIFTY 50 & BANKNIFTY
⏰ <b>Scan Interval:</b> 5 minutes
✅ <b>Status:</b> LIVE

📈 Signals will appear here automatically!
"""
            asyncio.run(self.telegram.send_message(message))
        except Exception as e:
            print(f"Startup message error: {e}")
    
    def is_market_hours(self):
        """Check if within market hours"""
        now = datetime.now(IST)
        current_time = now.time()
        
        # Market hours: 9:15 AM to 3:30 PM IST
        market_open = datetime.strptime("09:15", "%H:%M").time()
        market_close = datetime.strptime("15:30", "%H:%M").time()
        
        # Skip weekends
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        return market_open <= current_time <= market_close
    
    def scan_markets(self):
        """Scan all symbols and generate signals"""
        if not self.is_running:
            print("⚠️  Bot not initialized properly")
            return
        
        if not self.is_market_hours():
            print(f"⏸️  Outside market hours - {datetime.now(IST).strftime('%H:%M:%S IST')}")
            return
        
        print(f"\n{'='*70}")
        print(f"🔍 MARKET SCAN - {datetime.now(IST).strftime('%d-%m-%Y %H:%M:%S IST')}")
        print(f"{'='*70}")
        
        for symbol in TRADING_SYMBOLS:
            try:
                signal = self.signal_gen.analyze(symbol)
                
                if signal:
                    print(f"\n   🎯 SIGNAL GENERATED!")
                    print(f"   📍 {signal['direction']} {signal['symbol']} {signal['strike']}")
                    print(f"   📊 Confidence: {signal['confidence']}%")
                    
                    # Send to Telegram
                    asyncio.run(self.telegram.send_signal(signal))
                    
                    # Wait a bit between signals
                    time.sleep(2)
                    
            except Exception as e:
                print(f"   ❌ Error analyzing {symbol}: {e}")
        
        print(f"\n{'='*70}")
        print(f"⏳ Next scan in {SCAN_INTERVAL_MINUTES} minutes")
        print(f"{'='*70}\n")
    
    def run(self):
        """Main bot loop"""
        if not self.is_running:
            print("\n❌ Bot cannot start - initialization failed")
            print("💡 Set REQUEST_TOKEN or ACCESS_TOKEN environment variable")
            return
        
        print("\n🚀 Bot is LIVE and monitoring markets!")
        print(f"📱 Signals will be sent to Telegram chat: {TELEGRAM_CHAT_ID}")
        print(f"⏱️  Scanning every {SCAN_INTERVAL_MINUTES} minutes during market hours")
        print("\n🛑 Press Ctrl+C to stop\n")
        
        # Schedule periodic scans
        schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(self.scan_markets)
        
        # Initial scan
        self.scan_markets()
        
        # Keep running
        while True:
            try:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds
            except KeyboardInterrupt:
                print("\n\n🛑 Bot stopped by user")
                break
            except Exception as e:
                print(f"\n❌ Error in main loop: {e}")
                time.sleep(60)

# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    try:
        bot = TradingBot()
        bot.run()
    except Exception as e:
        print(f"\n❌ Fatal Error: {e}")
        import traceback
        traceback.print_exc()
