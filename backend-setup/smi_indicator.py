"""
Stochastic Momentum Index (SMI) Indicator Module

This module calculates the Stochastic Momentum Index to help detect:
- Trend exhaustion
- Momentum divergences
- Overbought/oversold conditions
- Trend reversal signals

The SMI is more sensitive than regular RSI and helps identify when trends are ending.
"""

import pandas as pd
import numpy as np
import json
import time
from datetime import datetime
import threading
import traceback

class SMIIndicator:
    def __init__(self, k_period=10, d_period=3, smoothing_period=3):
        """
        Initialize SMI Indicator
        
        Args:
            k_period: Period for %K calculation (default 10)
            d_period: Period for %D smoothing (default 3)
            smoothing_period: Additional smoothing period (default 3)
        """
        self.k_period = k_period
        self.d_period = d_period
        self.smoothing_period = smoothing_period
        self.smi_data = {}  # Store SMI data by symbol and timeframe
        
    def calculate_smi(self, df, high_col='high', low_col='low', close_col='close'):
        """
        Calculate Stochastic Momentum Index
        
        Args:
            df: DataFrame with OHLC data
            high_col: Column name for high prices
            low_col: Column name for low prices
            close_col: Column name for close prices
            
        Returns:
            DataFrame with SMI values added
        """
        try:
            if df.empty or len(df) < self.k_period + self.d_period + self.smoothing_period:
                # Not enough data
                df['SMI_K'] = np.nan
                df['SMI_D'] = np.nan
                df['SMI_Signal'] = 'NEUTRAL'
                df['SMI_Momentum'] = 'NEUTRAL'
                df['SMI_Divergence'] = False
                return df
            
            # Calculate highest high and lowest low over k_period
            df['HH'] = df[high_col].rolling(window=self.k_period).max()
            df['LL'] = df[low_col].rolling(window=self.k_period).min()
            
            # Calculate the middle point of the range
            df['HL_Mid'] = (df['HH'] + df['LL']) / 2
            
            # Calculate the distance from close to middle point
            df['Close_Mid_Diff'] = df[close_col] - df['HL_Mid']
            
            # Calculate the range
            df['HL_Range'] = df['HH'] - df['LL']
            
            # Smooth the differences
            df['Smooth_Close_Mid'] = df['Close_Mid_Diff'].rolling(window=self.smoothing_period).mean()
            df['Smooth_Range'] = df['HL_Range'].rolling(window=self.smoothing_period).mean()
            
            # Calculate SMI %K
            df['SMI_K'] = np.where(
                df['Smooth_Range'] != 0,
                (df['Smooth_Close_Mid'] / (df['Smooth_Range'] / 2)) * 100,
                0
            )
            
            # Calculate SMI %D (smoothed %K)
            df['SMI_D'] = df['SMI_K'].rolling(window=self.d_period).mean()
            
            # Generate signals
            df = self._generate_smi_signals(df)
            
            # Clean up intermediate columns
            df = df.drop(['HH', 'LL', 'HL_Mid', 'Close_Mid_Diff', 'HL_Range', 
                         'Smooth_Close_Mid', 'Smooth_Range'], axis=1)
            
            return df
            
        except Exception as e:
            print(f"Error calculating SMI: {e}")
            traceback.print_exc()
            # Return df with NaN values
            df['SMI_K'] = np.nan
            df['SMI_D'] = np.nan
            df['SMI_Signal'] = 'NEUTRAL'
            df['SMI_Momentum'] = 'NEUTRAL'
            df['SMI_Divergence'] = False
            return df
    
    def _generate_smi_signals(self, df):
        """
        Generate trading signals based on SMI values
        """
        try:
            # Initialize signal columns
            df['SMI_Signal'] = 'NEUTRAL'
            df['SMI_Momentum'] = 'NEUTRAL'
            df['SMI_Divergence'] = False
            
            # Define overbought/oversold levels
            overbought = 60  # Allow more room for trends
            oversold = -60   # Allow more room for trends
            
            # Generate basic signals
            conditions = [
                (df['SMI_K'] > overbought) & (df['SMI_D'] > overbought),
                (df['SMI_K'] < oversold) & (df['SMI_D'] < oversold),
                (df['SMI_K'] > df['SMI_D']) & (df['SMI_K'].shift(1) <= df['SMI_D'].shift(1)),
                (df['SMI_K'] < df['SMI_D']) & (df['SMI_K'].shift(1) >= df['SMI_D'].shift(1))
            ]
            
            choices = ['OVERBOUGHT', 'OVERSOLD', 'BULLISH_CROSS', 'BEARISH_CROSS']
            
            df['SMI_Signal'] = np.select(conditions, choices, default='NEUTRAL')
            
            # Calculate momentum direction
            df['SMI_Momentum'] = np.where(
                df['SMI_K'] > df['SMI_K'].shift(1), 'RISING',
                np.where(df['SMI_K'] < df['SMI_K'].shift(1), 'FALLING', 'FLAT')
            )
            
            # Detect divergences (simplified)
            if len(df) >= 20:
                # Look for price making higher highs but SMI making lower highs (bearish divergence)
                # or price making lower lows but SMI making higher lows (bullish divergence)
                
                price_highs = df['close'].rolling(window=5).max()
                price_lows = df['close'].rolling(window=5).min()
                smi_highs = df['SMI_K'].rolling(window=5).max()
                smi_lows = df['SMI_K'].rolling(window=5).min()
                
                # Bearish divergence: price higher high, SMI lower high
                bearish_div = (
                    (price_highs > price_highs.shift(5)) & 
                    (smi_highs < smi_highs.shift(5)) &
                    (df['SMI_K'] > 20)  # Only in upper range
                )
                
                # Bullish divergence: price lower low, SMI higher low
                bullish_div = (
                    (price_lows < price_lows.shift(5)) & 
                    (smi_lows > smi_lows.shift(5)) &
                    (df['SMI_K'] < -20)  # Only in lower range
                )
                
                df['SMI_Divergence'] = bearish_div | bullish_div
            
            return df
            
        except Exception as e:
            print(f"Error generating SMI signals: {e}")
            df['SMI_Signal'] = 'NEUTRAL'
            df['SMI_Momentum'] = 'NEUTRAL'
            df['SMI_Divergence'] = False
            return df
    
    def get_trend_strength(self, df, lookback=20):
        """
        Calculate trend strength based on SMI values
        
        Returns:
            dict: Trend strength analysis
        """
        try:
            if df.empty or 'SMI_K' not in df.columns or len(df) < lookback:
                return {
                    'strength': 'UNKNOWN',
                    'direction': 'NEUTRAL',
                    'exhaustion_risk': 'LOW',
                    'momentum_shift': False,
                    'confidence': 0
                }
            
            recent_df = df.tail(lookback)
            current_smi_k = df['SMI_K'].iloc[-1]
            current_smi_d = df['SMI_D'].iloc[-1]
            
            # Calculate trend direction
            if current_smi_k > 0 and current_smi_d > 0:
                direction = 'BULLISH'
            elif current_smi_k < 0 and current_smi_d < 0:
                direction = 'BEARISH'
            else:
                direction = 'NEUTRAL'
            
            # Calculate strength based on SMI range and consistency
            smi_range = abs(current_smi_k)
            if smi_range > 60:
                strength = 'VERY_STRONG'
            elif smi_range > 40:
                strength = 'STRONG'
            elif smi_range > 20:
                strength = 'MODERATE'
            else:
                strength = 'WEAK'
            
            # Check for exhaustion risk using dynamic logic
            ema_alignment = 'ALIGNED' if strength in ['STRONG', 'VERY_STRONG'] else 'WEAK'
            exhaustion_risk = self.get_dynamic_exhaustion_risk(current_smi_k, strength, ema_alignment)
            
            # Check for momentum shift
            momentum_shift = False
            if len(df) >= 5:
                recent_momentum = df['SMI_Momentum'].tail(3).tolist()
                if direction == 'BULLISH' and 'FALLING' in recent_momentum:
                    momentum_shift = True
                elif direction == 'BEARISH' and 'RISING' in recent_momentum:
                    momentum_shift = True
            
            # Calculate confidence based on consistency
            smi_k_trend = recent_df['SMI_K'].diff().mean()
            consistency = len(recent_df[recent_df['SMI_K'].diff().apply(lambda x: (x > 0) == (smi_k_trend > 0))]) / len(recent_df)
            confidence = int(consistency * 100)
            
            return {
                'strength': strength,
                'direction': direction,
                'exhaustion_risk': exhaustion_risk,
                'momentum_shift': momentum_shift,
                'confidence': confidence,
                'current_smi_k': current_smi_k,
                'current_smi_d': current_smi_d,
                'divergence_detected': df['SMI_Divergence'].iloc[-1] if 'SMI_Divergence' in df.columns else False
            }
            
        except Exception as e:
            print(f"Error calculating trend strength: {e}")
            return {
                'strength': 'UNKNOWN',
                'direction': 'NEUTRAL',
                'exhaustion_risk': 'LOW',
                'momentum_shift': False,
                'confidence': 0
            }
    
    def update_smi_data(self, symbol, timeframe, df):
        """
        Update SMI data for a symbol and timeframe
        """
        try:
            if symbol not in self.smi_data:
                self.smi_data[symbol] = {}
            
            # Calculate SMI
            df_with_smi = self.calculate_smi(df.copy())
            
            # Get trend strength analysis
            trend_analysis = self.get_trend_strength(df_with_smi)
            
            # Store the data
            self.smi_data[symbol][timeframe] = {
                'df': df_with_smi,
                'trend_analysis': trend_analysis,
                'last_update': datetime.now().isoformat()
            }
            
            return trend_analysis
            
        except Exception as e:
            print(f"Error updating SMI data for {symbol} {timeframe}: {e}")
            return None
    
    def get_smi_analysis_for_ai(self, symbol, timeframes=None):
        """
        Get SMI analysis formatted for AI consumption
        
        Args:
            symbol: Trading symbol
            timeframes: List of timeframes to include (default: all available)
            
        Returns:
            dict: Formatted SMI analysis for AI
        """
        try:
            if symbol not in self.smi_data:
                return {
                    'symbol': symbol,
                    'status': 'NO_DATA',
                    'message': 'No SMI data available for this symbol'
                }
            
            symbol_data = self.smi_data[symbol]
            
            if timeframes is None:
                timeframes = list(symbol_data.keys())
            
            analysis = {
                'symbol': symbol,
                'status': 'AVAILABLE',
                'timeframes': {},
                'overall_assessment': {},
                'warnings': []
            }
            
            # Collect data for each timeframe
            for tf in timeframes:
                if tf in symbol_data:
                    tf_data = symbol_data[tf]
                    trend_analysis = tf_data['trend_analysis']
                    df = tf_data['df']
                    
                    # Get current values
                    if not df.empty and 'SMI_K' in df.columns:
                        current_smi_k = df['SMI_K'].iloc[-1]
                        current_smi_d = df['SMI_D'].iloc[-1]
                        current_signal = df['SMI_Signal'].iloc[-1]
                        current_momentum = df['SMI_Momentum'].iloc[-1]
                        divergence = df['SMI_Divergence'].iloc[-1] if 'SMI_Divergence' in df.columns else False
                        
                        analysis['timeframes'][tf] = {
                            'smi_k': round(current_smi_k, 2),
                            'smi_d': round(current_smi_d, 2),
                            'signal': current_signal,
                            'momentum': current_momentum,
                            'divergence': divergence,
                            'trend_strength': trend_analysis['strength'],
                            'trend_direction': trend_analysis['direction'],
                            'exhaustion_risk': trend_analysis['exhaustion_risk'],
                            'momentum_shift': trend_analysis['momentum_shift'],
                            'confidence': trend_analysis['confidence']
                        }
            
            # Generate overall assessment
            if analysis['timeframes']:
                analysis['overall_assessment'] = self._generate_overall_assessment(analysis['timeframes'])
            
            return analysis
            
        except Exception as e:
            print(f"Error getting SMI analysis for AI: {e}")
            return {
                'symbol': symbol,
                'status': 'ERROR',
                'message': f'Error generating SMI analysis: {str(e)}'
            }
    
    def _generate_overall_assessment(self, timeframe_data):
        """
        Generate overall assessment from multiple timeframes
        """
        try:
            # Count signals across timeframes
            exhaustion_count = 0
            momentum_shift_count = 0
            divergence_count = 0
            strong_trends = 0
            
            directions = []
            strengths = []
            
            for tf, data in timeframe_data.items():
                if data['exhaustion_risk'] in ['HIGH', 'VERY_HIGH']:
                    exhaustion_count += 1
                
                if data['momentum_shift']:
                    momentum_shift_count += 1
                
                if data['divergence']:
                    divergence_count += 1
                
                if data['trend_strength'] in ['STRONG', 'VERY_STRONG']:
                    strong_trends += 1
                
                directions.append(data['trend_direction'])
                strengths.append(data['trend_strength'])
            
            total_timeframes = len(timeframe_data)
            
            # Generate warnings
            warnings = []
            if exhaustion_count >= total_timeframes * 0.5:
                warnings.append("HIGH_EXHAUSTION_RISK")
            
            if momentum_shift_count >= total_timeframes * 0.5:
                warnings.append("MOMENTUM_SHIFT_DETECTED")
            
            if divergence_count > 0:
                warnings.append("DIVERGENCE_DETECTED")
            
            # Determine overall trend consistency
            bullish_count = directions.count('BULLISH')
            bearish_count = directions.count('BEARISH')
            
            if bullish_count > bearish_count:
                overall_direction = 'BULLISH'
                consistency = bullish_count / total_timeframes
            elif bearish_count > bullish_count:
                overall_direction = 'BEARISH'
                consistency = bearish_count / total_timeframes
            else:
                overall_direction = 'MIXED'
                consistency = 0.5
            
            # Determine entry recommendation - less conservative for trending markets
            entry_recommendation = 'NEUTRAL'

            # More aggressive in strong trending markets
            strong_trend_ratio = strong_trends / total_timeframes

            if consistency > 0.7:
                if strong_trend_ratio >= 0.5:  # 50% or more timeframes show strong trend
                    # In strong trends, allow some exhaustion
                    if exhaustion_count <= total_timeframes * 0.5:  # Up to 50% can be exhausted
                        entry_recommendation = 'FAVORABLE'
                    else:
                        entry_recommendation = 'CAUTION'
                else:
                    # Weak trends - be more conservative
                    if exhaustion_count == 0 and momentum_shift_count == 0:
                        entry_recommendation = 'FAVORABLE'
                    else:
                        entry_recommendation = 'CAUTION'
            elif consistency > 0.5:
                entry_recommendation = 'CAUTION'
            elif divergence_count > 0:
                entry_recommendation = 'WAIT'
            
            return {
                'overall_direction': overall_direction,
                'trend_consistency': round(consistency * 100, 1),
                'entry_recommendation': entry_recommendation,
                'exhaustion_risk_level': 'HIGH' if exhaustion_count > 0 else 'LOW',
                'momentum_shift_risk': 'HIGH' if momentum_shift_count > 0 else 'LOW',
                'warnings': warnings,
                'strong_trend_count': strong_trends,
                'total_timeframes': total_timeframes
            }
            
        except Exception as e:
            print(f"Error generating overall assessment: {e}")
            return {
                'overall_direction': 'UNKNOWN',
                'trend_consistency': 0,
                'entry_recommendation': 'NEUTRAL',
                'exhaustion_risk_level': 'UNKNOWN',
                'momentum_shift_risk': 'UNKNOWN',
                'warnings': ['ANALYSIS_ERROR']
            }

    def get_dynamic_exhaustion_risk(self, current_smi_k, trend_strength, ema_alignment):
        abs_smi = abs(current_smi_k)
        
        # In strong trending markets, allow higher SMI levels
        if trend_strength in ['STRONG', 'VERY_STRONG'] and ema_alignment == 'ALIGNED':
            # Trending market - can stay overbought longer
            if abs_smi > 85:
                return 'VERY_HIGH'
            elif abs_smi > 70:
                return 'HIGH'
            elif abs_smi > 55:
                return 'MODERATE'
        else:
            # Ranging/weak trend - use stricter levels
            if abs_smi > 70:
                return 'VERY_HIGH'
            elif abs_smi > 50:
                return 'HIGH'
            elif abs_smi > 35:
                return 'MODERATE'
        
        return 'LOW'

# Global SMI indicator instance
smi_indicator = SMIIndicator()

def get_smi_analysis_for_symbol(symbol, timeframes=None):
    """
    Get SMI analysis for a symbol - to be called from s1.py
    
    Args:
        symbol: Trading symbol
        timeframes: List of timeframes to analyze
        
    Returns:
        dict: SMI analysis data for AI
    """
    return smi_indicator.get_smi_analysis_for_ai(symbol, timeframes)

def update_smi_for_symbol(symbol, timeframe, df):
    """
    Update SMI data for a symbol and timeframe - to be called from s1.py
    
    Args:
        symbol: Trading symbol
        timeframe: Timeframe key
        df: DataFrame with OHLC data
        
    Returns:
        dict: Trend analysis
    """
    return smi_indicator.update_smi_data(symbol, timeframe, df)

def start_smi_monitor():
    """
    Start the SMI monitoring system
    """
    print("SMI Indicator system started")
    print("SMI will help detect:")
    print("- Trend exhaustion signals")
    print("- Momentum divergences") 
    print("- Overbought/oversold conditions")
    print("- Trend reversal warnings")
    print("-" * 50)

if __name__ == "__main__":
    # Test the SMI indicator
    print("Testing SMI Indicator...")
    
    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    np.random.seed(42)
    
    # Generate sample OHLC data
    close_prices = 100 + np.cumsum(np.random.randn(100) * 0.5)
    high_prices = close_prices + np.random.rand(100) * 2
    low_prices = close_prices - np.random.rand(100) * 2
    open_prices = close_prices + np.random.randn(100) * 0.5
    
    test_df = pd.DataFrame({
        'time': dates,
        'open': open_prices,
        'high': high_prices,
        'low': low_prices,
        'close': close_prices,
        'volume': np.random.rand(100) * 1000
    })
    
    # Test SMI calculation
    smi = SMIIndicator()
    result_df = smi.calculate_smi(test_df)
    
    print(f"SMI calculation completed. Shape: {result_df.shape}")
    print(f"SMI_K range: {result_df['SMI_K'].min():.2f} to {result_df['SMI_K'].max():.2f}")
    print(f"SMI_D range: {result_df['SMI_D'].min():.2f} to {result_df['SMI_D'].max():.2f}")
    
    # Test trend analysis
    trend_analysis = smi.get_trend_strength(result_df)
    print(f"Trend Analysis: {trend_analysis}")
    
    # Test AI analysis format
    smi.update_smi_data('TESTUSDT', '15m', test_df)
    ai_analysis = smi.get_smi_analysis_for_ai('TESTUSDT')
    print(f"AI Analysis: {json.dumps(ai_analysis, indent=2)}") 