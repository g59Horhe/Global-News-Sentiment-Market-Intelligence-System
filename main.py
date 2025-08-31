import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import random
import re
import json
import os
from urllib.parse import urljoin, urlparse, quote
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
import sqlite3
from collections import Counter
import warnings
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
warnings.filterwarnings('ignore')

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.chrome.service import Service

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False
    print("⚠️  webdriver-manager not found. Install with: pip install webdriver-manager")

import matplotlib.pyplot as plt
try:
    import seaborn as sns
    sns.set_style("whitegrid")
except ImportError:
    pass

try:
    from wordcloud import WordCloud
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False

try:
    import nltk
    from nltk.sentiment import SentimentIntensityAnalyzer
    from nltk.tokenize import word_tokenize, sent_tokenize
    from nltk.corpus import stopwords
    from nltk.stem import WordNetLemmatizer
    
    nltk.download('vader_lexicon', quiet=True)
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    nltk.download('wordnet', quiet=True)
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False


@dataclass
class NewsArticle:
    title: str
    content: str
    url: str
    source: str
    published_date: str
    author: str
    category: str
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    keywords: List[str] = None


class NewsScrapingError(Exception):
    pass


class SimpleSentimentAnalyzer:
    def __init__(self):
        self.positive_words = {
            'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic', 'positive',
            'success', 'win', 'growth', 'increase', 'rise', 'gain', 'improve', 'better',
            'strong', 'confident', 'optimistic', 'breakthrough', 'achievement', 'boost',
            'surge', 'soar', 'rally', 'expand', 'advance', 'progress', 'victory'
        }
        self.negative_words = {
            'bad', 'terrible', 'awful', 'horrible', 'negative', 'fail', 'failure',
            'decline', 'decrease', 'fall', 'drop', 'loss', 'worse', 'crisis',
            'problem', 'issue', 'concern', 'worry', 'pessimistic', 'disaster',
            'crash', 'plunge', 'tumble', 'collapse', 'threat', 'risk', 'danger'
        }
    
    def polarity_scores(self, text):
        words = text.lower().split()
        positive_count = sum(1 for word in words if word in self.positive_words)
        negative_count = sum(1 for word in words if word in self.negative_words)
        
        total_words = len(words)
        if total_words == 0:
            return {'compound': 0.0, 'pos': 0.0, 'neu': 1.0, 'neg': 0.0}
        
        pos_score = positive_count / total_words
        neg_score = negative_count / total_words
        neu_score = max(0, 1.0 - pos_score - neg_score)
        
        compound = (pos_score - neg_score) * 2
        compound = max(-1, min(1, compound))
        
        return {
            'compound': compound,
            'pos': pos_score,
            'neu': neu_score,
            'neg': neg_score
        }


class FastSeleniumNewsScraper:
    def __init__(self, max_articles_per_source: int = 60, headless: bool = True, max_workers: int = 6):
        self.max_articles_per_source = max_articles_per_source
        self.headless = headless
        self.max_workers = max_workers
        self.drivers = []
        self.current_driver_index = 0
        self.driver_lock = threading.Lock()
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('selenium_news_scraping.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        if NLTK_AVAILABLE:
            self.sia = SentimentIntensityAnalyzer()
            self.lemmatizer = WordNetLemmatizer()
        else:
            self.sia = SimpleSentimentAnalyzer()
        
        self.init_drivers(self.max_workers)
        self.init_database()
        
        self.news_sources = {
            'bbc': {
                'base_urls': [
                    'https://www.bbc.com/news',
                    'https://www.bbc.com/news/world',
                    'https://www.bbc.com/news/business',
                    'https://www.bbc.com/news/technology',
                    'https://www.bbc.com/news/politics',
                    'https://www.bbc.com/news/health'
                ],
                'selectors': {
                    'article_links': [
                        'a[data-testid="internal-link"]',
                        'a[href*="/news/"]',
                        'h3 a',
                        '.media__link',
                        '.gs-c-promo-heading a',
                        '.gel-layout a',
                        'a[href*="2025"]',
                        'a[href*="2024"]',
                        '.nw-c-promo a',
                        '.gs-c-promo a',
                        '.media-list__item a',
                        '[data-testid="card-headline"] a',
                        '.block-link a',
                        '.media a',
                        '.promo a',
                        '.story-promo a'
                    ],
                    'title': [
                        'h1[data-testid="headline"]',
                        'h1',
                        '.story-body__h1',
                        '.headline',
                        '.article-headline__text'
                    ],
                    'content': [
                        '[data-component="text-block"] p',
                        '.story-body__inner p',
                        '.gel-body-copy',
                        'article p',
                        '.story-body p',
                        '.rich-text p'
                    ],
                    'date': [
                        'time[datetime]',
                        '[data-testid="timestamp"]',
                        '.date',
                        'time'
                    ],
                    'author': [
                        '[data-testid="byline-name"]',
                        '.byline__name',
                        '[rel="author"]',
                        '.story-body__byline',
                        '.author'
                    ]
                }
            },
            'guardian': {
                'base_urls': [
                    'https://www.theguardian.com/world',
                    'https://www.theguardian.com/business',
                    'https://www.theguardian.com/technology',
                    'https://www.theguardian.com/international',
                    'https://www.theguardian.com/uk-news',
                    'https://www.theguardian.com/politics'
                ],
                'selectors': {
                    'article_links': [
                        'a[data-link-name="article"]',
                        'a[href*="/2025/"]',
                        'a[href*="/2024/"]',
                        '.fc-item__link',
                        '.u-faux-block-link__overlay',
                        'h3 a',
                        '.headline a',
                        '.fc-item a',
                        '.content__headline a',
                        'a[data-component="GuardianLines"]',
                        '.dcr-lv2v9o a',
                        'article a',
                        'a[href*="/commentisfree/"]',
                        'a[href*="theguardian.com/"]'
                    ],
                    'title': [
                        'h1[data-gu-name="headline"]',
                        'h1',
                        '.content__headline',
                        '.article-header h1'
                    ],
                    'content': [
                        '.content__article-body p',
                        '.article-body p',
                        '#maincontent p',
                        '.content__main p',
                        'article p'
                    ],
                    'date': [
                        'time[datetime]',
                        '.content__dateline time',
                        '.timestamp',
                        'time'
                    ],
                    'author': [
                        '[data-component="meta-byline"] a',
                        '.byline a',
                        '.content__meta-container .contributor-full',
                        '.author-name'
                    ]
                }
            },
            'ap': {
                'base_urls': [
                    'https://apnews.com',
                    'https://apnews.com/hub/world-news',
                    'https://apnews.com/hub/business',
                    'https://apnews.com/hub/technology',
                    'https://apnews.com/world-news'
                ],
                'selectors': {
                    'article_links': [
                        'a[href*="/article/"]',
                        'a[data-key="card-headline"]',
                        '.Component-headline a',
                        'h3 a',
                        '.PagePromo-title a',
                        '.CardHeadline a',
                        'a[href*="/hub/"]',
                        '.Link a',
                        'article a'
                    ],
                    'title': [
                        'h1[data-key="card-headline"]',
                        'h1',
                        '.Page-headline',
                        '.Article-headline',
                        '.PagePromo-title'
                    ],
                    'content': [
                        '.RichTextStoryBody p',
                        '.Article p',
                        'div[data-key="article"] p',
                        '.main p',
                        'article p',
                        '.story-body p'
                    ],
                    'date': [
                        'bsp-timestamp',
                        'time[data-source="ap"]',
                        '.Timestamp',
                        'time',
                        '[data-key="timestamp"]'
                    ],
                    'author': [
                        '.Component-bylines',
                        '[data-key="byline"]',
                        '.Byline',
                        '.byline'
                    ]
                }
            },
            'cnn': {
                'base_urls': [
                    'https://www.cnn.com/world',
                    'https://www.cnn.com/business',
                    'https://www.cnn.com/tech',
                    'https://www.cnn.com',
                    'https://edition.cnn.com',
                    'https://www.cnn.com/politics'
                ],
                'selectors': {
                    'article_links': [
                        'a[href*="/2025/"]',
                        'a[href*="/2024/"]',
                        'a[data-link-type="article"]',
                        '.container__link',
                        'h3 a',
                        '.cd__headline-text a',
                        '.card a',
                        '.headline a',
                        'article a',
                        '.zone a[href*="/20"]',
                        'a[data-zjs*="headline"]',
                        '.cd__content a',
                        '.layout__wrapper a',
                        '.card-media a',
                        '.story a',
                        'a[href*="/index.html"]',
                        'a[href*="cnn.com"]'
                    ],
                    'title': [
                        'h1[data-editable="headlineText"]',
                        'h1',
                        '.headline__text',
                        '.pg-headline',
                        '[data-zn-id="headline"]',
                        '.Article__title'
                    ],
                    'content': [
                        '.zn-body__paragraph',
                        'p[data-zn-id="paragraph"]',
                        '.l-container p',
                        '.pg-body p',
                        '.BasicArticle__main p',
                        '.Article__content p',
                        'div[data-zn-id="paragraph"]',
                        '.wysiwyg p',
                        'article p',
                        '.body-text p'
                    ],
                    'date': [
                        '.timestamp',
                        'time',
                        '.metadata__date',
                        '[data-zn-id="timestamp"]'
                    ],
                    'author': [
                        '.byline__names',
                        '.metadata__byline',
                        '.BasicArticle__byline',
                        '[data-zn-id="byline"]'
                    ]
                }
            },
            'reuters': {
                'base_urls': [
                    'https://www.reuters.com/world/',
                    'https://www.reuters.com/business/',
                    'https://www.reuters.com/technology/',
                    'https://www.reuters.com/markets/',
                    'https://www.reuters.com/legal/',
                    'https://www.reuters.com/breakingviews/',
                    'https://www.reuters.com/business/finance/',
                    'https://www.reuters.com/business/energy/',
                    'https://www.reuters.com/world/americas/',
                    'https://www.reuters.com/world/europe/',
                    'https://www.reuters.com/world/asia-pacific/',
                    'https://www.reuters.com/world/middle-east/',
                    'https://www.reuters.com/world/africa/',
                    'https://www.reuters.com',
                    'https://www.reuters.com/news/archive'
                ],
                'selectors': {
                    'article_links': [
                        'a[data-testid="Heading"]',
                        'a[data-testid="Body"]',
                        'a[href*="/world/"]',
                        'a[href*="/business/"]',
                        'a[href*="/technology/"]',
                        'a[href*="/markets/"]',
                        'a[href*="/legal/"]',
                        'a[href*="/breakingviews/"]',
                        'h3 a',
                        'h2 a',
                        '.story-title a',
                        '.media-story-card__headline a',
                        '.story-card a',
                        'article a',
                        'a[href*="/news/"]',
                        'a[data-module="ArticleLink"]',
                        '.text__text a',
                        'a[href*="reuters.com/"]',
                        'a[data-testid*="Link"]',
                        '.story a',
                        '.headline a',
                        '.card a',
                        'a[href*="/2025/"]',
                        'a[href*="/2024/"]',
                        '.article-card a',
                        '.content a',
                        '[data-testid*="story-card"] a',
                        '.story-collection a',
                        '.item a',
                        '.news-headline a',
                        '.topic-container a',
                        '[data-testid="Card"] a'
                    ],
                    'title': [
                        'h1[data-testid="Heading"]',
                        'h1[data-testid="ArticleHeader:headline"]',
                        'h1',
                        '.ArticleHeader_headline',
                        '.headline',
                        '.title',
                        'header h1',
                        '[data-testid*="headline"]'
                    ],
                    'content': [
                        '[data-testid="paragraph-0"]',
                        '[data-testid="paragraph-1"]',
                        '[data-testid="paragraph-2"]',
                        '[data-testid="paragraph-3"]',
                        '[data-testid="paragraph-4"]',
                        'p[data-testid*="paragraph"]',
                        '.ArticleBody_container p',
                        'article p',
                        '.content p',
                        '.body p',
                        '.text p',
                        '[data-testid="ArticleBody"] p',
                        '.story-body p',
                        '.article-content p'
                    ],
                    'date': [
                        'time[datetime]',
                        '[data-testid="ArticleHeader:dateTime"]',
                        '.ArticleHeader_date',
                        '.timestamp',
                        '.date',
                        'time'
                    ],
                    'author': [
                        '[data-testid="AuthorByline"]',
                        '.ArticleHeader_author',
                        '.byline',
                        '.author',
                        '[data-testid*="author"]'
                    ]
                }
            }
        }
    
    def init_drivers(self, num_drivers=2):
        if not hasattr(self, 'logger'):
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        ]
        
        print(f"🔄 Initializing Selenium drivers for parallel processing...")
        print(f"🎯 Target: {num_drivers} drivers for {num_drivers} max workers")
        
        for i in range(num_drivers):
            try:
                options = Options()
                if self.headless:
                    options.add_argument('--headless=new')
                
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_argument('--disable-images')
                options.add_argument('--disable-plugins')
                options.add_argument('--disable-extensions')
                options.add_argument('--disable-background-timer-throttling')
                options.add_argument('--disable-backgrounding-occluded-windows')
                options.add_argument('--disable-renderer-backgrounding')
                options.add_argument('--window-size=1920,1080')
                options.add_argument(f'--user-agent={random.choice(user_agents)}')
                
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)
                
                prefs = {
                    "profile.managed_default_content_settings.images": 2,
                    "profile.default_content_setting_values.notifications": 2,
                    "profile.managed_default_content_settings.media_stream": 2,
                }
                options.add_experimental_option("prefs", prefs)
                
                if WEBDRIVER_MANAGER_AVAILABLE:
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(service=service, options=options)
                else:
                    driver = webdriver.Chrome(options=options)
                
                driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                driver.set_page_load_timeout(20)
                driver.implicitly_wait(3)
                
                self.drivers.append(driver)
                print(f"✅ Driver {i+1} initialized successfully")
                
            except Exception as e:
                self.logger.error(f"Failed to initialize driver {i+1}: {str(e)}")
                print(f"❌ Driver {i+1} failed: {str(e)}")
        
        if not self.drivers:
            raise Exception("Failed to initialize any drivers")
        
        self.logger.info(f"Initialized {len(self.drivers)} Selenium drivers for parallel processing")
        print(f"🎉 Successfully initialized {len(self.drivers)} drivers for parallel processing")
        print(f"🚀 Parallel processing ready with {len(self.drivers)} concurrent workers!")
    
    def get_driver(self):
        with self.driver_lock:
            driver = self.drivers[self.current_driver_index]
            self.current_driver_index = (self.current_driver_index + 1) % len(self.drivers)
            return driver
    
    def init_database(self):
        try:
            self.conn = sqlite3.connect('selenium_news_articles.db', check_same_thread=False)
            self.cursor = self.conn.cursor()
            
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL,
                    published_date TEXT,
                    author TEXT,
                    category TEXT,
                    sentiment_score REAL,
                    sentiment_label TEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    content_length INTEGER,
                    word_count INTEGER
                )
            ''')
            
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_source ON articles(source)
            ''')
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_sentiment ON articles(sentiment_label)
            ''')
            self.cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_date ON articles(published_date)
            ''')
            
            self.conn.commit()
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Database initialization failed: {str(e)}")
            raise
    
    def categorize_article(self, title, content):
        text = (title + " " + content).lower()
        
        categories = {
            'business': ['business', 'economy', 'market', 'stock', 'finance', 'trade', 'company', 'corporate', 'investment', 'bank'],
            'technology': ['technology', 'tech', 'ai', 'artificial intelligence', 'software', 'computer', 'digital', 'cyber', 'innovation', 'startup'],
            'politics': ['politics', 'government', 'election', 'vote', 'congress', 'senate', 'president', 'policy', 'law', 'parliament'],
            'health': ['health', 'medical', 'medicine', 'doctor', 'hospital', 'disease', 'virus', 'vaccine', 'treatment', 'healthcare'],
            'world': ['international', 'global', 'world', 'country', 'nation', 'war', 'conflict', 'diplomatic', 'foreign', 'crisis'],
            'sports': ['sport', 'game', 'team', 'player', 'match', 'championship', 'league', 'tournament', 'olympic', 'football']
        }
        
        category_scores = {}
        for category, keywords in categories.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > 0:
                category_scores[category] = score
        
        if category_scores:
            return max(category_scores.items(), key=lambda x: x[1])[0]
        return 'general'
    
    def analyze_sentiment(self, text):
        try:
            if hasattr(self.sia, 'polarity_scores'):
                scores = self.sia.polarity_scores(text)
                compound = scores['compound']
                
                if compound >= 0.05:
                    return compound, 'positive'
                elif compound <= -0.05:
                    return compound, 'negative'
                else:
                    return compound, 'neutral'
            else:
                return 0.0, 'neutral'
                
        except Exception as e:
            self.logger.error(f"Sentiment analysis error: {str(e)}")
            return 0.0, 'neutral'
    
    def fast_wait_and_scroll(self, driver, url, max_wait=3):
        try:
            WebDriverWait(driver, max_wait).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
            time.sleep(0.3)
            
        except TimeoutException:
            self.logger.debug(f"Timeout waiting for page load: {url}")
        except Exception as e:
            self.logger.debug(f"Scroll error for {url}: {str(e)}")
    
    def is_valid_article_url(self, url, source):
        if not url or '#' in url or 'javascript:' in url or 'mailto:' in url:
            return False
        
        invalid_patterns = [
            '/video/', '/live/', '/weather/', '/sport/', '/iplayer/', '/sounds/',
            '/programmes/', '/schedule/', '/contact/', '/about/', '/help/',
            '/terms/', '/privacy/', '/cookies/', '/accessibility/', '/newsletter',
            '/register', '/sign-in', '/login', '/profile', '/account', '/subscribe',
            '/gallery/', '/photos/', '/pictures/', '/images/', '/podcast/',
            '/radio/', '/tv/', '/media/', '/multimedia/', '/interactive/',
            'share', 'facebook.com', 'twitter.com', 'instagram.com', 'youtube.com',
            '/tags/', '/topics/', '/authors/', '/search', '/archive/',
            '/rss', '/feed', '/sitemap', 'mailto:', 'tel:', 'whatsapp:',
            '/corrections/', '/obituaries/', '/crossword/', '/sudoku/',
            '/horoscope/', '/games/', '/quiz/', '/competition/',
            '.pdf', '.jpg', '.png', '.gif', '.mp4', '.mp3',
            '/live-reporting/', '/coronavirus/', '/covid',
            '/election/', '/olympics/', '/world-cup/', '/champions-league/'
        ]
        
        url_lower = url.lower()
        for pattern in invalid_patterns:
            if pattern in url_lower:
                return False
        
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        
        date_patterns = [
            today.strftime("/%Y/%m/%d/"),
            yesterday.strftime("/%Y/%m/%d/"),
            today.strftime("/%Y-%m-%d"),
            yesterday.strftime("/%Y-%m-%d"),
            '/2025/', '/2024/'
        ]
        
        for pattern in date_patterns:
            if pattern in url:
                return True
        
        return True
    
    def optimize_reuters_scraping(self, driver, url):
        try:
            WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.TAG_NAME, "article"))
            )
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(0.5)
            
            overlay_selectors = [
                '[data-testid="TrustArcOverlay"]',
                '.trust-arc-overlay',
                '.cookie-banner',
                '.overlay',
                '.modal',
                '.popup'
            ]
            
            for selector in overlay_selectors:
                try:
                    overlay = driver.find_element(By.CSS_SELECTOR, selector)
                    if overlay.is_displayed():
                        driver.execute_script("arguments[0].style.display = 'none';", overlay)
                except:
                    continue
                    
            time.sleep(0.3)
            
        except Exception as e:
            self.logger.debug(f"Reuters optimization failed for {url}: {str(e)}")
    
    def extract_text_with_multiple_selectors(self, soup, selectors, source):
        for selector in selectors:
            try:
                elements = soup.select(selector)
                if elements:
                    text_parts = []
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        if text and len(text) > 10:
                            text_parts.append(text)
                    
                    if text_parts:
                        return ' '.join(text_parts)
                        
            except Exception as e:
                self.logger.debug(f"Selector {selector} failed for {source}: {str(e)}")
                continue
                
        return None
    
    def extract_article_content_fast(self, url, source, retries=0):
        for attempt in range(retries + 1):
            driver = None
            try:
                driver = self.get_driver()
                
                time.sleep(random.uniform(0.2, 0.8))
                driver.get(url)
                
                if source == 'reuters':
                    self.optimize_reuters_scraping(driver, url)
                else:
                    self.fast_wait_and_scroll(driver, url)
                    
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                config = self.news_sources[source]['selectors']
                
                title = "No title"
                for selector in config['title'][:3]:
                    try:
                        title_elem = soup.select_one(selector)
                        if title_elem and title_elem.get_text(strip=True):
                            title = title_elem.get_text(strip=True)
                            break
                    except:
                        continue
                
                content_parts = []
                for selector in config['content'][:4]:
                    try:
                        elements = soup.select(selector)
                        for elem in elements[:10]:
                            text = elem.get_text(strip=True)
                            if text and len(text) > 20:
                                content_parts.append(text)
                        
                        if len(content_parts) >= 3:
                            break
                    except:
                        continue
                
                content = ' '.join(content_parts) if content_parts else "No content"
                
                if len(content) < 100:
                    content = self.extract_text_with_multiple_selectors(soup, config['content'], source) or content
                
                author = "Unknown"
                for selector in config['author'][:2]:
                    try:
                        author_elem = soup.select_one(selector)
                        if author_elem and author_elem.get_text(strip=True):
                            author = author_elem.get_text(strip=True)
                            break
                    except:
                        continue
                
                published_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for selector in config['date'][:2]:
                    try:
                        date_elem = soup.select_one(selector)
                        if date_elem:
                            date_text = date_elem.get('datetime') or date_elem.get_text(strip=True)
                            if date_text:
                                published_date = date_text
                                break
                    except:
                        continue
                
                return {
                    'title': title,
                    'content': content,
                    'url': url,
                    'source': source,
                    'published_date': published_date,
                    'author': author
                }
                
            except Exception as e:
                self.logger.debug(f"Attempt {attempt + 1} failed for {url}: {str(e)}")
                if attempt < retries:
                    time.sleep(random.uniform(1, 3))
                continue
            
        return None
    
    def extract_article_links_fast(self, url, source):
        driver = None
        try:
            driver = self.get_driver()
            time.sleep(random.uniform(0.5, 1.5))
            
            driver.get(url)
            self.fast_wait_and_scroll(driver, url)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            links = set()
            config = self.news_sources[source]['selectors']
            
            for selector in config['article_links']:
                try:
                    elements = soup.select(selector)
                    for element in elements:
                        href = element.get('href')
                        if href and self.is_valid_article_url(href, source):
                            if href.startswith('/'):
                                base_domains = {
                                    'ap': 'https://apnews.com',
                                    'cnn': 'https://edition.cnn.com', 
                                    'bbc': 'https://www.bbc.com',
                                    'guardian': 'https://www.theguardian.com',
                                    'reuters': 'https://www.reuters.com'
                                }
                                href = base_domains.get(source, 'https://') + href
                            links.add(href)
                except:
                    continue
            
            if len(links) < 5:
                print("🔄 Trying fallback selectors...")
                fallback_selectors = [
                    'a[href*="2025"]',
                    'a[href*="2024"]',  
                    'article a',
                    '.article a',
                    'h3 a',
                    'h2 a',
                    'h1 a',
                    '.headline a',
                    '.title a',
                    '.story a',
                    '.card a',
                    '.link a',
                    'a[href*="/news/"]',
                    'a[href*="/article/"]',
                    'a[href*="/story/"]'
                ]
                
                for selector in fallback_selectors:
                    try:
                        elements = soup.select(selector)
                        for element in elements[:20]:
                            href = element.get('href')
                            if href and self.is_valid_article_url(href, source):
                                if href.startswith('/'):
                                    base_domains = {
                                        'ap': 'https://apnews.com',
                                        'cnn': 'https://edition.cnn.com', 
                                        'bbc': 'https://www.bbc.com',
                                        'guardian': 'https://www.theguardian.com',
                                        'reuters': 'https://www.reuters.com'
                                    }
                                    href = base_domains.get(source, 'https://') + href
                                links.add(href)
                        
                        if len(links) >= 10:
                            break
                    except:
                        continue
            
            unique_links = list(links)[:self.max_articles_per_source]
            self.logger.info(f"Extracted {len(unique_links)} article links for {source}")
            print(f"🎯 Total valid links found: {len(unique_links)}")
            
            return unique_links
            
        except Exception as e:
            self.logger.error(f"Failed to extract links from {url}: {str(e)}")
            return []
        
    def scrape_source_fast(self, source):
        print(f"\n🚀 TURBO MODE: Starting {source.upper()} with parallel link extraction")
        start_time = time.time()
        all_articles = []
        
        config = self.news_sources[source]
        print(f"📍 {source.upper()}: {len(config['base_urls'])} URLs to process")
        
        all_links = []
        
        with ThreadPoolExecutor(max_workers=min(3, len(self.drivers))) as executor:
            future_to_url = {
                executor.submit(self.extract_article_links_fast, url, source): url 
                for url in config['base_urls']
            }
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    links = future.result(timeout=30)
                    all_links.extend(links)
                    print(f"✅ {url}: {len(links)} links")
                except Exception as e:
                    print(f"❌ {url}: Failed - {str(e)[:50]}")
        
        unique_links = list(set(all_links))[:self.max_articles_per_source]
        print(f"🎯 {source.upper()}: Processing {len(unique_links)} unique articles")
        
        if not unique_links:
            print(f"⚠️  No valid links found for {source}")
            return []
        
        with ThreadPoolExecutor(max_workers=min(len(self.drivers), 6)) as executor:
            future_to_url = {
                executor.submit(self.extract_article_content_fast, link, source, 1): link 
                for link in unique_links
            }
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    article_data = future.result(timeout=15)
                    if article_data and len(article_data.get('content', '')) > 100:
                        category = self.categorize_article(article_data['title'], article_data['content'])
                        sentiment_score, sentiment_label = self.analyze_sentiment(
                            article_data['title'] + " " + article_data['content']
                        )
                        
                        article_data.update({
                            'category': category,
                            'sentiment_score': sentiment_score,
                            'sentiment_label': sentiment_label
                        })
                        
                        all_articles.append(article_data)
                        
                        if len(all_articles) % 10 == 0:
                            print(f"📊 {source.upper()}: {len(all_articles)} articles processed")
                    
                except Exception as e:
                    self.logger.debug(f"Failed to process {url}: {str(e)}")
        
        elapsed = time.time() - start_time
        articles_per_min = (len(all_articles) / elapsed) * 60 if elapsed > 0 else 0
        
        print(f"🎉 {source.upper()}: {len(all_articles)} articles in {elapsed:.1f}s ({articles_per_min:.1f}/min)")
        return all_articles
    
    def scrape_all_sources_fast(self):
        print("🚀 Starting TURBO NEWS SCRAPING with PARALLEL SOURCE processing")
        start_time = time.time()
        all_articles = []
        
        USE_PARALLEL_SOURCES = False
        
        if USE_PARALLEL_SOURCES and len(self.drivers) >= len(self.news_sources):
            print("🔥 EXPERIMENTAL: Processing all sources in parallel!")
            
            with ThreadPoolExecutor(max_workers=min(len(self.news_sources), len(self.drivers))) as executor:
                future_to_source = {
                    executor.submit(self.scrape_source_fast, source): source 
                    for source in self.news_sources.keys()
                }
                
                for future in as_completed(future_to_source):
                    source = future_to_source[future]
                    try:
                        articles = future.result(timeout=180)
                        all_articles.extend(articles)
                        print(f"🎯 {source.upper()} completed: {len(articles)} articles")
                    except Exception as e:
                        print(f"❌ {source.upper()} failed: {str(e)[:100]}")
                        self.logger.error(f"Failed to scrape source {source}: {str(e)}")
        else:
            for source in self.news_sources.keys():
                try:
                    print(f"\n{'='*50}")
                    print(f"📰 PROCESSING: {source.upper()}")
                    print(f"{'='*50}")
                    
                    articles = self.scrape_source_fast(source)
                    if articles:
                        all_articles.extend(articles)
                        print(f"✅ {source.upper()}: Successfully collected {len(articles)} articles")
                    else:
                        print(f"❌ {source.upper()}: No articles collected")
                        
                except Exception as e:
                    print(f"❌ {source.upper()} failed: {str(e)}")
                    self.logger.error(f"Failed to scrape source {source}: {str(e)}")
        
        if all_articles:
            self.save_articles_to_database(all_articles)
        
        total_time = time.time() - start_time
        self.display_performance_metrics(all_articles, total_time)
        
        return all_articles
    
    def save_articles_to_database(self, articles):
        try:
            for article in articles:
                content_length = len(article.get('content', ''))
                word_count = len(article.get('content', '').split())
                
                self.cursor.execute('''
                    INSERT OR REPLACE INTO articles 
                    (title, content, url, source, published_date, author, category, 
                     sentiment_score, sentiment_label, content_length, word_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    article['title'],
                    article['content'],
                    article['url'],
                    article['source'],
                    article['published_date'],
                    article['author'],
                    article['category'],
                    article['sentiment_score'],
                    article['sentiment_label'],
                    content_length,
                    word_count
                ))
            
            self.conn.commit()
            self.logger.info(f"Saved {len(articles)} articles to database")
            
        except Exception as e:
            self.logger.error(f"Database save error: {str(e)}")
    
    def display_performance_metrics(self, articles, total_time):
        if not articles:
            print("❌ No articles collected")
            return
        
        print(f"\n{'='*60}")
        print(f"🎉 SELENIUM NEWS SCRAPING COMPLETED!")
        print(f"{'='*60}")
        
        articles_per_second = len(articles) / total_time if total_time > 0 else 0
        articles_per_minute = articles_per_second * 60
        avg_content_length = sum(len(article.get('content', '')) for article in articles) / len(articles)
        
        print(f"PERFORMANCE METRICS:")
        print(f"Total time: {total_time:.1f} seconds")
        print(f"Articles per second: {articles_per_second:.2f}")
        print(f"Total articles: {len(articles)}")
        print(f"Average content length: {avg_content_length:.0f} characters")
        print(f"Parallel efficiency: {articles_per_minute:.1f} articles/minute")
        
        source_stats = {}
        for article in articles:
            source = article['source']
            source_stats[source] = source_stats.get(source, 0) + 1
        
        print(f"\n📊 SOURCE BREAKDOWN:")
        for source, count in sorted(source_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(articles)) * 100
            rate_per_min = (count / total_time) * 60 if total_time > 0 else 0
            
            if rate_per_min >= 2.0:
                status = "🚀 FAST"
            elif rate_per_min >= 1.0:
                status = "✅ OK"
            else:
                status = "🐌 SLOW"
            
            print(f"   {source.upper():10} | {count:3d} articles ({percentage:5.1f}%) | {rate_per_min:.1f}/min | {status}")
        
        category_stats = {}
        for article in articles:
            category = article.get('category', 'unknown')
            category_stats[category] = category_stats.get(category, 0) + 1
        
        print(f"\n📈 CATEGORY BREAKDOWN:")
        for category, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(articles)) * 100
            print(f"   {category.title():12} | {count:3d} articles ({percentage:5.1f}%)")
        
        sentiment_stats = {}
        for article in articles:
            sentiment = article.get('sentiment_label', 'neutral')
            sentiment_stats[sentiment] = sentiment_stats.get(sentiment, 0) + 1
        
        print(f"\n😊 SENTIMENT BREAKDOWN:")
        sentiment_emojis = {'positive': '😊', 'negative': '😔', 'neutral': '😐'}
        for sentiment, count in sorted(sentiment_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(articles)) * 100
            emoji = sentiment_emojis.get(sentiment, '❓')
            print(f"   {emoji} {sentiment.title():8} | {count:3d} articles ({percentage:5.1f}%)")
        
        unique_sources = len(source_stats)
        total_sources = len(self.news_sources)
        success_rate = (unique_sources / total_sources) * 100
        
        print(f"\n🎯 SUCCESS METRICS:")
        print(f"Source success rate: {success_rate:.1f}% ({unique_sources}/{total_sources} sources)")
        
        if articles_per_minute >= 8:
            performance = "🚀 EXCELLENT"
        elif articles_per_minute >= 5:
            performance = "✅ GOOD"
        elif articles_per_minute >= 3:
            performance = "⚠️  MODERATE"
        else:
            performance = "🐌 SLOW"
        
        print(f"{performance} - {articles_per_minute:.1f} articles/minute")
        print(f"{'='*60}")
    
    def cleanup(self):
        print("🧹 Cleaning up resources...")
        for i, driver in enumerate(self.drivers):
            try:
                driver.quit()
                print(f"✅ Closed driver {i+1}")
            except Exception as e:
                print(f"⚠️  Error closing driver {i+1}: {str(e)}")
        
        if hasattr(self, 'conn'):
            try:
                self.conn.close()
                print("✅ Database connection closed")
            except Exception as e:
                print(f"⚠️  Error closing database: {str(e)}")


class SeleniumSentimentAnalyzer:
    def __init__(self, db_path: str = 'selenium_news_articles.db'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        
        if NLTK_AVAILABLE:
            self.sia = SentimentIntensityAnalyzer()
        else:
            self.sia = SimpleSentimentAnalyzer()
    
    def get_articles_from_db(self, limit: int = None, source: str = None, 
                           start_date: str = None, end_date: str = None) -> pd.DataFrame:
        query = "SELECT * FROM articles WHERE 1=1"
        params = []
        
        if source:
            query += " AND source = ?"
            params.append(source)
        
        if start_date:
            query += " AND scraped_at >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND scraped_at <= ?"
            params.append(end_date)
        
        query += " ORDER BY scraped_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        return pd.read_sql_query(query, self.conn, params=params)
    
    def analyze_sentiment_trends(self, df: pd.DataFrame) -> Dict:
        if df.empty:
            return {}
        
        df['scraped_at'] = pd.to_datetime(df['scraped_at'])
        df['date'] = df['scraped_at'].dt.date
        
        trends = {
            'daily_sentiment': df.groupby('date')['sentiment_score'].mean(),
            'source_sentiment': df.groupby('source')['sentiment_score'].mean(),
            'category_sentiment': df.groupby('category')['sentiment_score'].mean(),
            'sentiment_distribution': df['sentiment_label'].value_counts(),
            'avg_content_length': df['content_length'].mean(),
            'total_articles': len(df),
            'date_range': {
                'start': df['scraped_at'].min(),
                'end': df['scraped_at'].max()
            }
        }
        
        return trends
    
    def create_visualizations(self, df: pd.DataFrame, save_path: str = 'selenium_news_dashboard.png'):
        if df.empty:
            print("No data available for visualization")
            return
        
        plt.style.use('seaborn-v0_8')
        fig, axes = plt.subplots(2, 3, figsize=(20, 12))
        fig.suptitle('📊 News Sentiment Analysis Dashboard', fontsize=16, fontweight='bold')
        
        df['scraped_at'] = pd.to_datetime(df['scraped_at'])
        
        sentiment_counts = df['sentiment_label'].value_counts()
        colors = ['#2ecc71', '#e74c3c', '#95a5a6']
        axes[0, 0].pie(sentiment_counts.values, labels=sentiment_counts.index, autopct='%1.1f%%', 
                       colors=colors, startangle=90)
        axes[0, 0].set_title('😊 Sentiment Distribution')
        
        source_counts = df['source'].value_counts()
        axes[0, 1].bar(source_counts.index, source_counts.values, color='#3498db')
        axes[0, 1].set_title('📰 Articles by Source')
        axes[0, 1].tick_params(axis='x', rotation=45)
        
        category_counts = df['category'].value_counts().head(8)
        axes[0, 2].barh(category_counts.index, category_counts.values, color='#9b59b6')
        axes[0, 2].set_title('📈 Articles by Category')
        
        df_recent = df[df['scraped_at'] >= df['scraped_at'].max() - pd.Timedelta(days=7)]
        if not df_recent.empty:
            daily_sentiment = df_recent.groupby(df_recent['scraped_at'].dt.date)['sentiment_score'].mean()
            axes[1, 0].plot(daily_sentiment.index, daily_sentiment.values, marker='o', color='#e67e22', linewidth=2)
            axes[1, 0].set_title('📅 Daily Sentiment Trend (Last 7 Days)')
            axes[1, 0].tick_params(axis='x', rotation=45)
            axes[1, 0].axhline(y=0, color='gray', linestyle='--', alpha=0.7)
        
        source_sentiment = df.groupby('source')['sentiment_score'].mean()
        bars = axes[1, 1].bar(source_sentiment.index, source_sentiment.values)
        axes[1, 1].set_title('🎯 Average Sentiment by Source')
        axes[1, 1].tick_params(axis='x', rotation=45)
        axes[1, 1].axhline(y=0, color='gray', linestyle='--', alpha=0.7)
        
        for bar, score in zip(bars, source_sentiment.values):
            color = '#2ecc71' if score > 0 else '#e74c3c' if score < 0 else '#95a5a6'
            bar.set_color(color)
        
        content_lengths = df['content_length'].hist(bins=30, ax=axes[1, 2], color='#1abc9c', alpha=0.7)
        axes[1, 2].set_title('📝 Content Length Distribution')
        axes[1, 2].set_xlabel('Content Length (characters)')
        axes[1, 2].set_ylabel('Frequency')
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"📊 Dashboard saved as '{save_path}'")
        
        return fig
    
    def create_wordcloud(self, df: pd.DataFrame, sentiment: str = 'all', save_path: str = None):
        if not WORDCLOUD_AVAILABLE:
            print("WordCloud not available. Install with: pip install wordcloud")
            return
        
        if df.empty:
            print("No data available for word cloud")
            return
        
        if sentiment != 'all':
            df = df[df['sentiment_label'] == sentiment]
        
        if df.empty:
            print(f"No articles found for sentiment: {sentiment}")
            return
        
        text = ' '.join(df['title'].fillna('') + ' ' + df['content'].fillna(''))
        
        try:
            if NLTK_AVAILABLE:
                stop_words = set(stopwords.words('english'))
            else:
                stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        except:
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        
        wordcloud = WordCloud(
            width=1200, height=600,
            background_color='white',
            stopwords=stop_words,
            max_words=100,
            colormap='viridis',
            relative_scaling=0.5,
            random_state=42
        ).generate(text)
        
        plt.figure(figsize=(15, 8))
        plt.imshow(wordcloud, interpolation='bilinear')
        plt.axis('off')
        plt.title(f'Word Cloud - {sentiment.title() if sentiment != "all" else "All"} Sentiment', 
                 fontsize=16, fontweight='bold', pad=20)
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"💭 Word cloud saved as '{save_path}'")
        
        plt.show()
        return wordcloud
    
    def generate_summary_report(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "No articles found in database."
        
        trends = self.analyze_sentiment_trends(df)
        
        report = f"""
📰 NEWS SENTIMENT ANALYSIS REPORT
{'='*50}

📊 OVERVIEW:
   Total Articles: {trends['total_articles']:,}
   Date Range: {trends['date_range']['start'].strftime('%Y-%m-%d')} to {trends['date_range']['end'].strftime('%Y-%m-%d')}
   Average Content Length: {trends['avg_content_length']:.0f} characters

😊 SENTIMENT DISTRIBUTION:
"""
        
        for sentiment, count in trends['sentiment_distribution'].items():
            percentage = (count / trends['total_articles']) * 100
            emoji = {'positive': '😊', 'negative': '😔', 'neutral': '😐'}.get(sentiment, '❓')
            report += f"   {emoji} {sentiment.title()}: {count:,} ({percentage:.1f}%)\n"
        
        report += f"\n📰 TOP SOURCES BY SENTIMENT:\n"
        source_sentiment_sorted = trends['source_sentiment'].sort_values(ascending=False)
        for source, avg_sentiment in source_sentiment_sorted.items():
            emoji = '😊' if avg_sentiment > 0.1 else '😔' if avg_sentiment < -0.1 else '😐'
            report += f"   {emoji} {source.upper()}: {avg_sentiment:.3f}\n"
        
        report += f"\n📈 CATEGORY INSIGHTS:\n"
        category_sentiment_sorted = trends['category_sentiment'].sort_values(ascending=False)
        for category, avg_sentiment in category_sentiment_sorted.items():
            emoji = '😊' if avg_sentiment > 0.1 else '😔' if avg_sentiment < -0.1 else '😐'
            report += f"   {emoji} {category.title()}: {avg_sentiment:.3f}\n"
        
        overall_sentiment = df['sentiment_score'].mean()
        market_mood = "🚀 BULLISH" if overall_sentiment > 0.1 else "📉 BEARISH" if overall_sentiment < -0.1 else "⚖️ NEUTRAL"
        
        report += f"""
🎯 MARKET SENTIMENT ANALYSIS:
   Overall Score: {overall_sentiment:.3f}
   Market Classification: {market_mood}
   
💡 INSIGHTS:
   Most Positive Source: {source_sentiment_sorted.index[0].upper()} ({source_sentiment_sorted.iloc[0]:.3f})
   Most Negative Source: {source_sentiment_sorted.index[-1].upper()} ({source_sentiment_sorted.iloc[-1]:.3f})
   Most Covered Category: {df['category'].value_counts().index[0].title()} ({df['category'].value_counts().iloc[0]} articles)
"""
        
        return report
    
    def close(self):
        if hasattr(self, 'conn'):
            self.conn.close()


def main():
    scraper = FastSeleniumNewsScraper(max_articles_per_source=60, headless=True, max_workers=6)
    
    try:
        print("🚀 Starting comprehensive news sentiment analysis...")
        articles = scraper.scrape_all_sources_fast()
        
        if articles:
            print(f"\n🎉 SUCCESS! Collected {len(articles)} articles!")
            print("✓ Data saved to database")
            print("✓ Ready for analysis")
            
            analyzer = SeleniumSentimentAnalyzer()
            
            try:
                df = analyzer.get_articles_from_db(limit=1000)
                
                if not df.empty:
                    print(f"\n📊 Creating visualizations...")
                    analyzer.create_visualizations(df)
                    
                    print(f"\n📋 Generating summary report...")
                    report = analyzer.generate_summary_report(df)
                    print(report)
                else:
                    print("⚠️  No articles found in database for analysis")
                    
            except Exception as e:
                print(f"⚠️  Analysis error: {str(e)}")
            finally:
                analyzer.close()
        else:
            print("❌ No articles were collected")
            
    except Exception as e:
        print(f"❌ Scraping failed: {str(e)}")
        scraper.logger.error(f"Main execution failed: {str(e)}")
    finally:
        scraper.cleanup()

if __name__ == "__main__":
    main()
