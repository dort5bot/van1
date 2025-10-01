"""
analysis/score.py
Skor hesaplama & model birleşimi - Tüm alt analizlerin sonuçlarıyla karma skor üretme
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

@dataclass
class ScoreConfig:
    """Skor hesaplama konfigürasyonu"""
    # Ağırlıklar
    module_weights: Dict[str, float] = None
    # Normalizasyon parametreleri
    z_score_threshold: float = 2.0
    min_confidence: float = 0.3
    # Risk ayarları
    max_drawdown_weight: float = 0.15
    volatility_penalty: float = 0.1
    
    def __post_init__(self):
        if self.module_weights is None:
            self.module_weights = {
                "tremo": 0.20,      # Trend ve momentum
                "regime": 0.18,     # Piyasa modu
                "derivs": 0.16,     # Türev piyasa
                "causality": 0.14,  # Lider-takipçi
                "orderflow": 0.12,  # Likidite
                "onchain": 0.10,    # On-chain veri
                "risk": 0.10        # Risk yönetimi
            }

class ScoreAggregator:
    """Gelişmiş skor agregasyon sınıfı"""
    
    def __init__(self, config: Optional[ScoreConfig] = None):
        self.config = config or ScoreConfig()
        self._confidence_cache = {}
        
    def calculate_confidence(self, scores: Dict[str, float]) -> float:
        """Skorların güvenilirliğini hesapla"""
        try:
            valid_scores = [s for s in scores.values() if s is not None]
            if not valid_scores:
                return 0.0
                
            # Varyans tabanlı güven ölçümü
            variance = np.var(valid_scores)
            max_variance = 1.0  # -1 to +1 aralığı için maksimum varyans
            confidence = 1.0 - min(variance / max_variance, 1.0)
            
            # Çok sayıda geçerli skor güveni artırır
            score_ratio = len(valid_scores) / len(scores)
            confidence *= score_ratio
            
            return max(confidence, 0.0)
            
        except Exception as e:
            logger.error(f"Güven hesaplama hatası: {e}")
            return 0.0
    
    def normalize_scores(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Skorları normalize et ve outlier'ları temizle"""
        normalized = {}
        
        for module, score in scores.items():
            if score is None:
                normalized[module] = 0.0
                continue
                
            # Z-score normalizasyonu
            try:
                # Basit clipping ile normalizasyon
                clipped_score = max(-1.0, min(1.0, score))
                
                # Softmax benzeri normalizasyon
                exp_score = np.exp(clipped_score * 2)  # Scale için
                normalized[module] = (exp_score - 1) / (exp_score + 1)
                
            except Exception as e:
                logger.warning(f"Skor normalizasyon hatası {module}: {e}")
                normalized[module] = 0.0
                
        return normalized
    
    def calculate_final_score(self, module_scores: Dict[str, float]) -> Dict[str, float]:
        """
        Nihai trade sinyali skorunu hesapla
        
        Returns:
            Dict containing final_score, confidence, and component scores
        """
        try:
            # Normalize scores
            normalized_scores = self.normalize_scores(module_scores)
            
            # Calculate weighted average
            final_score = 0.0
            total_weight = 0.0
            
            for module, score in normalized_scores.items():
                weight = self.config.module_weights.get(module, 0.0)
                final_score += score * weight
                total_weight += weight
            
            if total_weight > 0:
                final_score /= total_weight
            else:
                final_score = 0.0
            
            # Confidence calculation
            confidence = self.calculate_confidence(normalized_scores)
            
            # Apply confidence adjustment
            adjusted_score = final_score * confidence
            
            return {
                "final_score": float(adjusted_score),
                "raw_score": float(final_score),
                "confidence": float(confidence),
                "component_scores": normalized_scores,
                "weights": self.config.module_weights
            }
            
        except Exception as e:
            logger.error(f"Final skor hesaplama hatası: {e}")
            return {
                "final_score": 0.0,
                "raw_score": 0.0,
                "confidence": 0.0,
                "component_scores": {},
                "weights": self.config.module_weights
            }

# Singleton instance
_score_aggregator = None

def get_score_aggregator(config: Optional[ScoreConfig] = None) -> ScoreAggregator:
    """ScoreAggregator singleton instance'ını döndür"""
    global _score_aggregator
    if _score_aggregator is None:
        _score_aggregator = ScoreAggregator(config)
    return _score_aggregator