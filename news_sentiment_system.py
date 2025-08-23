#!/usr/bin/env python3

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
warnings.filterwarnings('ignore')

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

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
    scraping_method: str = "requests"
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
            'strong', 'confident', 'optimistic', 'breakthrough', 'achievement'
        }
        self.negative_words = {
            'bad', 'terrible', 'awful', 'horrible', 'negative', 'fail', 'failure',
            'decline', 'decrease', 'fall', 'drop', 'loss', 'worse', 'crisis',
            'problem', 'issue', 'concern', 'worry', 'pessimistic', 'disaster'
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
        neu_score = 1.0 - pos_score - neg_score
        
        compound = pos_score - neg_score
        
        return {
            'compound': compound,
            'pos': pos_score,
            'neu': neu_score,
            'neg': neg_score
        }

class SeleniumManager:
    
    def __init__(self):
        self.driver = None
        self.setup_driver()
    
    def setup_driver(self):
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium not available.")
        
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    def get_page_selenium(self, url: str, wait_time: int = 10) -> BeautifulSoup:
        try:
            self.driver.get(url)
            
            WebDriverWait(self.driver, wait_time).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            time.sleep(random.uniform(2, 4))
            
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            page_source = self.driver.page_source
            return BeautifulSoup(page_source, 'html.parser')
            
        except Exception as e:
            raise NewsScrapingError(f"Selenium error for {url}: {str(e)}")
    
    def close(self):
        if self.driver:
            self.driver.quit()

class EnhancedNewsScraper:
    
    def __init__(self, max_articles_per_source: int = 25):
        self.max_articles_per_source = max_articles_per_source
        
        if SELENIUM_AVAILABLE:
            try:
                self.selenium_manager = SeleniumManager()
            except Exception:
                self.selenium_manager = None
        else:
            self.selenium_manager = None
        
        self.sessions = self.create_multiple_sessions()
        self.current_session_index = 0
        
        if NLTK_AVAILABLE:
            self.sia = SentimentIntensityAnalyzer()
            self.lemmatizer = WordNetLemmatizer()
        else:
            self.sia = SimpleSentimentAnalyzer()
            self.lemmatizer = None
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('enhanced_scraping.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        self.init_database()
        
        self.selenium_sources = {
            'ap': {
                'base_url': 'https://apnews.com',
                'sections': ['world-news', 'business', 'technology'],
                'section_urls': {
                    'world-news': 'https://apnews.com/hub/world-news',
                    'business': 'https://apnews.com/hub/business',
                    'technology': 'https://apnews.com/hub/technology'
                },
                'selectors': {
                    'article_links': 'a[href*="/article/"]',
                    'title': 'h1, .Page-headline, [data-key="card-headline"]',
                    'content': '.RichTextStoryBody p, .Article p, div[data-key="article"] p, .main p',
                    'date': 'time, .Timestamp, [data-key="timestamp"]',
                    'author': '.Component-bylines, [data-key="byline"], .Byline'
                }
            },
            'cnn': {
                'base_url': 'https://edition.cnn.com',
                'sections': ['world', 'business', 'tech'],
                'section_urls': {
                    'world': 'https://edition.cnn.com/world',
                    'business': 'https://edition.cnn.com/business',
                    'tech': 'https://edition.cnn.com/business/tech'
                },
                'selectors': {
                    'article_links': 'a[href*="/2024/"], a[href*="/2025/"]',
                    'title': 'h1, .headline__text, .pg-headline, [data-zn-id="headline"], .Article__title',
                    'content': '.zn-body__paragraph, .el-editorial-source p, p[data-zn-id="paragraph"], .l-container p, .pg-body p, .BasicArticle__main p, .Article__content p, div[data-zn-id="paragraph"], .wysiwyg p, article p, .body-text p',
                    'date': '.timestamp, time, .metadata__date, [data-zn-id="timestamp"]',
                    'author': '.byline__names, .metadata__byline, .BasicArticle__byline, [data-zn-id="byline"]'
                }
            }
        }
        
        self.requests_sources = {
            'bbc': {
                'base_url': 'https://www.bbc.com/news',
                'sections': ['world', 'business', 'technology'],
                'selectors': {
                    'article_links': 'a[href*="/news/articles/"], a[href*="/news/world-"], a[href*="/news/business-"], a[href*="/news/technology-"]',
                    'title': 'h1, .story-body__h1, #main-heading',
                    'content': '[data-component="text-block"] p, article p, .story-body p, .story-body__inner p, main p, .gel-body-copy',
                    'date': 'time, .date, [data-datetime]',
                    'author': '.byline__name, [rel="author"], .story-body__byline'
                }
            },
            'guardian': {
                'base_url': 'https://www.theguardian.com',
                'sections': ['world', 'business', 'technology'],
                'selectors': {
                    'article_links': 'a[href*="/2025/aug/"], a[href*="/2025/jul/"], a[href*="/2025/jun/"], a[href*="/2024/aug/"], a[href*="/2024/jul/"], a[href*="/2024/jun/"], a[href*="/2024/"], a[href*="/2025/"]',
                    'title': 'h1, .content__headline',
                    'content': '.content__article-body p, .article-body p, #maincontent p, .content__main p',
                    'date': 'time, .content__dateline time',
                    'author': '.byline a, .content__meta-container .contributor-full'
                }
            },
            'ap': {
                'base_url': 'https://apnews.com',
                'sections': ['world-news', 'business', 'technology'],
                'section_urls': {
                    'world-news': 'https://apnews.com/hub/world-news',
                    'business': 'https://apnews.com/hub/business',
                    'technology': 'https://apnews.com/hub/technology'
                },
                'selectors': {
                    'article_links': 'a[href*="/article/"]',
                    'title': 'h1, .Page-headline, [data-key="card-headline"]',
                    'content': '.RichTextStoryBody p, .Article p, div[data-key="article"] p, .main p',
                    'date': 'time, .Timestamp, [data-key="timestamp"]',
                    'author': '.Component-bylines, [data-key="byline"], .Byline'
                }
            },
            'cnn': {
                'base_url': 'https://edition.cnn.com',
                'sections': ['world', 'business', 'tech'],
                'section_urls': {
                    'world': 'https://edition.cnn.com/world',
                    'business': 'https://edition.cnn.com/business',
                    'tech': 'https://edition.cnn.com/business/tech'
                },
                'selectors': {
                    'article_links': 'a[href*="/2024/"], a[href*="/2025/"]',
                    'title': 'h1, .headline__text, .pg-headline, [data-zn-id="headline"], .Article__title',
                    'content': '.zn-body__paragraph, .el-editorial-source p, p[data-zn-id="paragraph"], .l-container p, .pg-body p, .BasicArticle__main p, .Article__content p, div[data-zn-id="paragraph"], .wysiwyg p, article p, .body-text p',
                    'date': '.timestamp, time, .metadata__date, [data-zn-id="timestamp"]',
                    'author': '.byline__names, .metadata__byline, .BasicArticle__byline, [data-zn-id="byline"]'
                }
            }
        }
    
    def create_multiple_sessions(self):
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0'
        ]
        
        sessions = []
        for i, ua in enumerate(user_agents):
            session = requests.Session()
            session.headers.update({
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"' if i % 2 == 0 else '"macOS"'
            })
            
            # Add some randomization to make requests look more human
            session.cookies.set('session_id', f'sess_{i}_{random.randint(1000, 9999)}')
            sessions.append(session)
        
        return sessions
    
    def get_session(self):
        session = self.sessions[self.current_session_index]
        self.current_session_index = (self.current_session_index + 1) % len(self.sessions)
        return session
    
    def init_database(self):
        self.conn = sqlite3.connect('enhanced_news_articles.db')
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT,
                url TEXT UNIQUE,
                source TEXT,
                published_date TEXT,
                author TEXT,
                category TEXT,
                scraping_method TEXT,
                sentiment_score REAL,
                sentiment_label TEXT,
                keywords TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def get_page_content_requests(self, url: str, source: str = None, retries: int = 3) -> BeautifulSoup:
        for attempt in range(retries):
            try:
                session = self.get_session()
                time.sleep(random.uniform(2, 5))
                
                response = session.get(url, timeout=25, allow_redirects=True)
                response.raise_for_status()
                
                if len(response.text) < 500:
                    if attempt < retries - 1:
                        continue
                    else:
                        raise NewsScrapingError(f"Insufficient content from {url}")
                
                return BeautifulSoup(response.content, 'html.parser')
                
            except requests.exceptions.RequestException as e:
                if attempt < retries - 1:
                    time.sleep((attempt + 1) * 3)
                    continue
                else:
                    raise NewsScrapingError(f"Failed to fetch {url}: {str(e)}")
    
    def extract_article_links(self, soup: BeautifulSoup, source_config: Dict, source: str) -> List[str]:
        links = []
        selector = source_config['selectors']['article_links']
        
        selectors_to_try = selector.split(', ')
        
        for sel in selectors_to_try:
            link_elements = soup.select(sel.strip())
            if link_elements:
                break
        
        for link_elem in link_elements:
            href = link_elem.get('href')
            if href:
                if href.startswith('/'):
                    if source == 'ap':
                        full_url = f"https://apnews.com{href}"
                    elif source == 'cnn':
                        full_url = f"https://edition.cnn.com{href}"
                    else:
                        full_url = urljoin(source_config['base_url'], href)
                else:
                    full_url = href
                
                if self.is_valid_article_url(full_url, source):
                    links.append(full_url)
        
        unique_links = list(set(links))[:self.max_articles_per_source]
        self.logger.info(f"Found {len(unique_links)} valid article links for {source}")
        
        return unique_links
    
    def is_valid_article_url(self, url: str, source: str) -> bool:
        invalid_patterns = [
            '/video/', '/gallery/', '/live/', '/sport/', '/sports/',
            '/opinion/', '/weather/', '/entertainment/', '/podcasts/',
            'javascript:', 'mailto:', '/newsletter', '/subscribe'
        ]
        
        url_lower = url.lower()
        return not any(pattern in url_lower for pattern in invalid_patterns)
    
    def extract_article_content(self, url: str, source: str, method: str = "requests") -> Optional[NewsArticle]:
        try:
            if method == "selenium" and self.selenium_manager:
                soup = self.selenium_manager.get_page_selenium(url)
            else:
                soup = self.get_page_content_requests(url, source)
            
            if method == "selenium":
                config = self.selenium_sources.get(source, {}).get('selectors', {})
            else:
                config = self.requests_sources.get(source, {}).get('selectors', {})
            
            if not config:
                self.logger.warning(f"No config found for {source} with method {method}")
                return None
            
            title = "No title"
            if 'title' in config:
                title_selectors = config['title'].split(', ')
                for title_selector in title_selectors:
                    title_elem = soup.select_one(title_selector.strip())
                    if title_elem and title_elem.get_text().strip():
                        title = title_elem.get_text().strip()
                        break
            
            content_parts = []
            if 'content' in config:
                content_selectors = config['content'].split(', ')
                for content_selector in content_selectors:
                    content_elems = soup.select(content_selector.strip())
                    if content_elems:
                        content_parts.extend([elem.get_text().strip() for elem in content_elems if elem.get_text().strip()])
                        if content_parts:
                            break
            
            content = ' '.join(content_parts)
            
            published_date = str(datetime.now().date())
            if 'date' in config:
                date_selectors = config['date'].split(', ')
                for date_selector in date_selectors:
                    date_elem = soup.select_one(date_selector.strip())
                    if date_elem:
                        date_value = date_elem.get('datetime') or date_elem.get('content') or date_elem.get_text().strip()
                        if date_value:
                            published_date = date_value[:10] if len(date_value) > 10 else date_value
                            break
            
            author = "Unknown"
            if 'author' in config:
                author_selectors = config['author'].split(', ')
                for author_selector in author_selectors:
                    author_elem = soup.select_one(author_selector.strip())
                    if author_elem and author_elem.get_text().strip():
                        author = author_elem.get_text().strip()[:100]
                        break
            
            if len(content) < 50:
                self.logger.warning(f"Skipping article with insufficient content: {url}")
                return None
            
            article = NewsArticle(
                title=title[:500],
                content=content[:5000],
                url=url,
                source=source,
                published_date=published_date,
                author=author,
                category=self.determine_category(url),
                scraping_method=method
            )
            
            self.analyze_sentiment(article)
            
            return article
            
        except Exception as e:
            self.logger.error(f"Error extracting article from {url} using {method}: {str(e)}")
            return None
    
    def determine_category(self, url: str) -> str:
        categories = {
            'business': ['business', 'economy', 'finance', 'markets', 'money'],
            'technology': ['technology', 'tech', 'science', 'digital'],
            'world': ['world', 'international', 'global'],
            'politics': ['politics', 'government', 'election'],
            'health': ['health', 'medical', 'coronavirus', 'covid']
        }
        
        url_lower = url.lower()
        for category, keywords in categories.items():
            if any(keyword in url_lower for keyword in keywords):
                return category
        return 'general'
    
    def analyze_sentiment(self, article: NewsArticle):
        text = f"{article.title} {article.content}"
        scores = self.sia.polarity_scores(text)
        
        article.sentiment_score = scores['compound']
        
        if scores['compound'] >= 0.05:
            article.sentiment_label = 'positive'
        elif scores['compound'] <= -0.05:
            article.sentiment_label = 'negative'
        else:
            article.sentiment_label = 'neutral'
        
        article.keywords = self.extract_keywords(text)
    
    def extract_keywords(self, text: str, top_n: int = 10) -> List[str]:
        try:
            if NLTK_AVAILABLE:
                words = word_tokenize(text.lower())
                stop_words = set(stopwords.words('english'))
                
                keywords = []
                for word in words:
                    if (word.isalpha() and 
                        len(word) > 3 and 
                        word not in stop_words):
                        keywords.append(self.lemmatizer.lemmatize(word))
                
                counter = Counter(keywords)
                return [word for word, count in counter.most_common(top_n)]
            else:
                words = text.lower().split()
                common_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
                keywords = [word for word in words if len(word) > 3 and word not in common_words and word.isalpha()]
                counter = Counter(keywords)
                return [word for word, count in counter.most_common(top_n)]
        except:
            return []
    
    def save_article(self, article: NewsArticle):
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO articles 
                (title, content, url, source, published_date, author, category, 
                 scraping_method, sentiment_score, sentiment_label, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                article.title, article.content, article.url, article.source,
                article.published_date, article.author, article.category,
                article.scraping_method, article.sentiment_score, article.sentiment_label,
                json.dumps(article.keywords)
            ))
            self.conn.commit()
        except Exception as e:
            self.logger.error(f"Error saving article to database: {str(e)}")
    
    def scrape_source_selenium(self, source: str) -> List[NewsArticle]:
        self.logger.info(f"Starting Selenium scraping for {source}")
        articles = []
        
        if not self.selenium_manager:
            self.logger.error(f"Selenium not available for {source}")
            return articles
        
        try:
            config = self.selenium_sources[source]
            
            for section in config['sections']:
                self.logger.info(f"Selenium scraping {source} - {section}")
                
                if 'section_urls' in config and section in config['section_urls']:
                    section_url = config['section_urls'][section]
                else:
                    section_url = f"{config['base_url']}/{section}"
                
                try:
                    soup = self.selenium_manager.get_page_selenium(section_url)
                    article_links = self.extract_article_links(soup, config, source)
                    
                    if not article_links:
                        self.logger.warning(f"No article links found for {source} - {section}")
                        continue
                    
                    self.logger.info(f"Found {len(article_links)} article links in {section}")
                    
                    for i, link in enumerate(article_links[:15]):
                        try:
                            time.sleep(random.uniform(3, 6))
                            
                            article = self.extract_article_content(link, source, method="selenium")
                            if article and len(article.content) > 50:
                                articles.append(article)
                                self.save_article(article)
                                self.logger.info(f"Selenium {source}: {article.title[:50]}...")
                                
                        except Exception as e:
                            self.logger.error(f"Selenium error scraping {link}: {str(e)}")
                            continue
                        
                except Exception as e:
                    self.logger.error(f"Selenium error in section {section}: {str(e)}")
                    continue
                
                time.sleep(random.uniform(4, 7))
                
        except Exception as e:
            self.logger.error(f"Selenium error scraping source {source}: {str(e)}")
        
        self.logger.info(f"Selenium completed {source}: {len(articles)} articles scraped")
        return articles
    
    def scrape_source_requests(self, source: str) -> List[NewsArticle]:
        self.logger.info(f"Starting Requests scraping for {source}")
        articles = []
        
        try:
            config = self.requests_sources[source]
            
            for section in config['sections']:
                self.logger.info(f"Requests scraping {source} - {section}")
                
                # Use section_urls if available, otherwise construct from base_url
                if 'section_urls' in config and section in config['section_urls']:
                    section_url = config['section_urls'][section]
                else:
                    section_url = f"{config['base_url']}/{section}"
                
                try:
                    soup = self.get_page_content_requests(section_url, source)
                    article_links = self.extract_article_links(soup, config, source)
                    
                    if not article_links:
                        self.logger.warning(f"No article links found for {source} - {section}")
                        continue
                    
                    self.logger.info(f"Found {len(article_links)} article links in {section}")
                    
                    for i, link in enumerate(article_links[:15]):
                        try:
                            time.sleep(random.uniform(2, 4))
                            
                            article = self.extract_article_content(link, source, method="requests")
                            if article and len(article.content) > 50:
                                articles.append(article)
                                self.save_article(article)
                                self.logger.info(f"Requests {source}: {article.title[:50]}...")
                                
                        except Exception as e:
                            self.logger.error(f"Requests error scraping {link}: {str(e)}")
                            continue
                        
                except Exception as e:
                    self.logger.error(f"Requests error in section {section}: {str(e)}")
                    continue
                
                time.sleep(random.uniform(3, 5))
                
        except Exception as e:
            self.logger.error(f"Requests error scraping source {source}: {str(e)}")
        
        self.logger.info(f"Requests completed {source}: {len(articles)} articles scraped")
        return articles
    
    def scrape_all_sources(self) -> List[NewsArticle]:
        all_articles = []
        
        # Try all sources with requests method first (more reliable)
        requests_count = 0
        for source in self.requests_sources.keys():
            try:
                time.sleep(random.uniform(5, 8))
                articles = self.scrape_source_requests(source)
                all_articles.extend(articles)
                requests_count += len(articles)
                
            except Exception as e:
                self.logger.error(f"Critical Requests error for {source}: {str(e)}")
                continue
        
        # Only try selenium for sources that failed with requests
        selenium_count = 0
        failed_sources = []
        for source in self.selenium_sources.keys():
            source_articles = [a for a in all_articles if a.source == source]
            if len(source_articles) == 0:  # No articles found with requests
                failed_sources.append(source)
        
        if failed_sources and self.selenium_manager:
            self.logger.info(f"Attempting Selenium fallback for sources: {', '.join(failed_sources)}")
            for source in failed_sources:
                try:
                    time.sleep(random.uniform(8, 12))
                    articles = self.scrape_source_selenium(source)
                    all_articles.extend(articles)
                    selenium_count += len(articles)
                
                except Exception as e:
                    self.logger.error(f"Critical Selenium fallback error for {source}: {str(e)}")
                    continue
        
        self.print_scraping_summary(all_articles)
        return all_articles
    
    def print_scraping_summary(self, articles: List[NewsArticle]):
        if not articles:
            print("No articles were successfully scraped.")
            return
            
        source_counts = {}
        category_counts = {}
        method_counts = {'selenium': 0, 'requests': 0}
        
        for article in articles:
            source_counts[article.source] = source_counts.get(article.source, 0) + 1
            category_counts[article.category] = category_counts.get(article.category, 0) + 1
            method_counts[article.scraping_method] = method_counts.get(article.scraping_method, 0)
        
        print("SCRAPING SUMMARY")
        
        print("SELENIUM SOURCES:")
        for source in self.selenium_sources.keys():
            count = source_counts.get(source, 0)
            status = "SUCCESS" if count > 0 else "FAILED"
            print(f"   {source.upper()}: {count} articles | {status}")
        
        print("REQUESTS SOURCES:")
        for source in self.requests_sources.keys():
            count = source_counts.get(source, 0)
            status = "SUCCESS" if count > 0 else "FAILED"
            print(f"   {source.upper()}: {count} articles | {status}")
        
        print("BY CATEGORY:")
        for category, count in sorted(category_counts.items()):
            print(f"   {category.capitalize()}: {count} articles")
        
        print("BY METHOD:")
        print(f"   Selenium: {method_counts['selenium']} articles")
        print(f"   Requests: {method_counts['requests']} articles")
        
        print(f"TOTAL ARTICLES: {len(articles)}")
        success_sources = len([s for s in source_counts if source_counts[s] > 0])
        print(f"SUCCESSFUL SOURCES: {success_sources}/4")
    
    def __del__(self):
        if hasattr(self, 'selenium_manager') and self.selenium_manager:
            self.selenium_manager.close()
        if hasattr(self, 'conn'):
            self.conn.close()

class EnhancedSentimentAnalyzer:
    
    def __init__(self, db_path: str = 'enhanced_news_articles.db'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        
    def load_articles(self) -> pd.DataFrame:
        query = '''
            SELECT * FROM articles 
            WHERE scraped_at >= datetime('now', '-7 days')
            ORDER BY scraped_at DESC
        '''
        return pd.read_sql_query(query, self.conn)
    
    def method_performance_analysis(self) -> Dict:
        df = self.load_articles()
        
        if len(df) == 0:
            return {}
        
        method_analysis = {}
        for method in df['scraping_method'].unique():
            method_df = df[df['scraping_method'] == method]
            if len(method_df) > 0:
                method_analysis[method] = {
                    'article_count': len(method_df),
                    'avg_content_length': method_df['content'].str.len().mean(),
                    'avg_sentiment': method_df['sentiment_score'].mean(),
                    'sentiment_std': method_df['sentiment_score'].std(),
                    'sources': list(method_df['source'].unique()),
                    'success_rate': len(method_df['source'].unique()) / 2.0
                }
        
        return method_analysis
    
    def sentiment_distribution(self) -> Dict:
        df = self.load_articles()
        
        distribution = {
            'overall': df['sentiment_label'].value_counts().to_dict(),
            'by_source': df.groupby('source')['sentiment_label'].value_counts().unstack(fill_value=0).to_dict(),
            'by_category': df.groupby('category')['sentiment_label'].value_counts().unstack(fill_value=0).to_dict(),
            'by_method': df.groupby('scraping_method')['sentiment_label'].value_counts().unstack(fill_value=0).to_dict(),
            'sentiment_scores': {
                'mean': df['sentiment_score'].mean(),
                'std': df['sentiment_score'].std(),
                'selenium_mean': df[df['scraping_method'] == 'selenium']['sentiment_score'].mean() if len(df[df['scraping_method'] == 'selenium']) > 0 else 0,
                'requests_mean': df[df['scraping_method'] == 'requests']['sentiment_score'].mean() if len(df[df['scraping_method'] == 'requests']) > 0 else 0
            }
        }
        
        return distribution
    
    def trending_topics(self, top_n: int = 20) -> List[tuple]:
        df = self.load_articles()
        all_keywords = []
        
        for keywords_str in df['keywords'].dropna():
            try:
                keywords = json.loads(keywords_str)
                all_keywords.extend(keywords)
            except:
                continue
        
        counter = Counter(all_keywords)
        return counter.most_common(top_n)
    
    def cross_method_comparison(self) -> Dict:
        df = self.load_articles()
        
        comparison = {}
        for method in df['scraping_method'].unique():
            method_df = df[df['scraping_method'] == method]
            if len(method_df) > 0:
                comparison[method] = {
                    'total_articles': len(method_df),
                    'avg_content_length': method_df['content'].str.len().mean(),
                    'avg_sentiment': method_df['sentiment_score'].mean(),
                    'sentiment_consistency': method_df['sentiment_score'].std(),
                    'category_diversity': len(method_df['category'].unique()),
                    'source_coverage': len(method_df['source'].unique()),
                    'success_rate': len(method_df['source'].unique()) / 2.0
                }
        
        return comparison

def create_enhanced_dashboard(df):
    fig, axes = plt.subplots(4, 3, figsize=(24, 20))
    fig.suptitle('Mixed Method Global News Sentiment Analysis Dashboard', fontsize=20, fontweight='bold')
    
    sentiment_counts = df['sentiment_label'].value_counts()
    colors = ['#ff6b6b' if x == 'negative' else '#4ecdc4' if x == 'positive' else '#95a5a6' 
             for x in sentiment_counts.index]
    axes[0, 0].pie(sentiment_counts.values, labels=sentiment_counts.index, autopct='%1.1f%%', 
                  colors=colors, startangle=90)
    axes[0, 0].set_title('Overall Sentiment Distribution', fontsize=12, fontweight='bold')
    
    if 'scraping_method' in df.columns and len(df['scraping_method'].unique()) > 1:
        method_counts = df['scraping_method'].value_counts()
        colors_method = ['#3498db', '#e74c3c'][:len(method_counts)]
        bars = axes[0, 1].bar(method_counts.index, method_counts.values, color=colors_method)
        axes[0, 1].set_title('Articles by Scraping Method', fontsize=12, fontweight='bold')
        axes[0, 1].set_xlabel('Scraping Method')
        axes[0, 1].set_ylabel('Article Count')
        
        for bar in bars:
            height = bar.get_height()
            axes[0, 1].text(bar.get_x() + bar.get_width()/2., height + 1,
                           f'{int(height)}', ha='center', va='bottom', fontsize=10)
    
    if 'scraping_method' in df.columns and len(df['scraping_method'].unique()) > 1:
        method_sentiment = pd.crosstab(df['scraping_method'], df['sentiment_label'])
        method_sentiment.plot(kind='bar', ax=axes[0, 2], color=['#ff6b6b', '#95a5a6', '#4ecdc4'])
        axes[0, 2].set_title('Sentiment by Scraping Method', fontsize=12, fontweight='bold')
        axes[0, 2].set_xlabel('Scraping Method')
        axes[0, 2].set_ylabel('Article Count')
        axes[0, 2].legend(title='Sentiment')
        axes[0, 2].tick_params(axis='x', rotation=45)
    
    if len(df['source'].unique()) > 1:
        source_counts = df['source'].value_counts()
        
        selenium_sources = ['ap', 'cnn']
        colors_source = ['#3498db' if source in selenium_sources else '#e74c3c' 
                        for source in source_counts.index]
        
        bars = axes[1, 0].bar(source_counts.index, source_counts.values, color=colors_source)
        axes[1, 0].set_title('Collection Success by Source', fontsize=12, fontweight='bold')
        axes[1, 0].set_xlabel('News Source')
        axes[1, 0].set_ylabel('Article Count')
        axes[1, 0].tick_params(axis='x', rotation=45)
        
        selenium_patch = plt.Rectangle((0,0),1,1,fc='#3498db', label='Selenium')
        requests_patch = plt.Rectangle((0,0),1,1,fc='#e74c3c', label='Requests')
        axes[1, 0].legend(handles=[selenium_patch, requests_patch])
        
        for bar in bars:
            height = bar.get_height()
            axes[1, 0].text(bar.get_x() + bar.get_width()/2., height + 0.5,
                           f'{int(height)}', ha='center', va='bottom', fontsize=9)
    
    if 'scraping_method' in df.columns:
        df['content_length'] = df['content'].str.len()
        method_quality = df.groupby('scraping_method')['content_length'].mean()
        bars = axes[1, 1].bar(method_quality.index, method_quality.values, 
                             color=['#3498db', '#e74c3c'][:len(method_quality)])
        axes[1, 1].set_title('Content Quality by Method', fontsize=12, fontweight='bold')
        axes[1, 1].set_xlabel('Scraping Method')
        axes[1, 1].set_ylabel('Average Content Length')
        
        for bar in bars:
            height = bar.get_height()
            axes[1, 1].text(bar.get_x() + bar.get_width()/2., height + 50,
                           f'{int(height)}', ha='center', va='bottom', fontsize=10)
    
    axes[1, 2].hist(df['sentiment_score'], bins=25, alpha=0.7, color='#3498db', edgecolor='black')
    axes[1, 2].axvline(df['sentiment_score'].mean(), color='red', linestyle='--', 
                      label=f'Mean: {df["sentiment_score"].mean():.3f}')
    axes[1, 2].set_title('Sentiment Score Distribution', fontsize=12, fontweight='bold')
    axes[1, 2].set_xlabel('Sentiment Score')
    axes[1, 2].set_ylabel('Frequency')
    axes[1, 2].legend()
    
    if len(df['category'].unique()) > 1:
        category_sentiment = pd.crosstab(df['category'], df['sentiment_label'])
        category_sentiment.plot(kind='bar', ax=axes[2, 0], color=['#ff6b6b', '#95a5a6', '#4ecdc4'])
        axes[2, 0].set_title('Sentiment by Category', fontsize=12, fontweight='bold')
        axes[2, 0].set_xlabel('Category')
        axes[2, 0].set_ylabel('Article Count')
        axes[2, 0].tick_params(axis='x', rotation=45)
        axes[2, 0].legend(title='Sentiment')
    
    df['scraped_date'] = pd.to_datetime(df['scraped_at']).dt.date
    if len(df['scraped_date'].unique()) > 1:
        timeline_data = df.groupby(['scraped_date', 'sentiment_label']).size().unstack(fill_value=0)
        timeline_data.plot(ax=axes[2, 1], color=['#ff6b6b', '#95a5a6', '#4ecdc4'], 
                          linewidth=2, marker='o')
        axes[2, 1].set_title('Sentiment Timeline', fontsize=12, fontweight='bold')
        axes[2, 1].set_xlabel('Date')
        axes[2, 1].set_ylabel('Article Count')
        axes[2, 1].legend(title='Sentiment')
        axes[2, 1].grid(True, alpha=0.3)
    
    if len(df['source'].unique()) > 1:
        avg_sentiment = df.groupby('source')['sentiment_score'].mean().sort_values(ascending=True)
        
        selenium_sources = ['ap', 'cnn']
        colors_bar = ['#3498db' if source in selenium_sources else '#e74c3c' 
                     for source in avg_sentiment.index]
        
        bars = axes[2, 2].barh(avg_sentiment.index, avg_sentiment.values, color=colors_bar)
        axes[2, 2].set_title('Average Sentiment by Source', fontsize=12, fontweight='bold')
        axes[2, 2].set_xlabel('Average Sentiment Score')
        axes[2, 2].axvline(0, color='black', linestyle='-', alpha=0.5)
        
        for i, bar in enumerate(bars):
            width = bar.get_width()
            axes[2, 2].text(width + (0.01 if width >= 0 else -0.01), 
                           bar.get_y() + bar.get_height()/2,
                           f'{width:.3f}', ha='left' if width >= 0 else 'right', 
                           va='center', fontsize=9)
    
    if 'scraping_method' in df.columns and len(df['scraping_method'].unique()) > 1:
        method_sentiment_avg = df.groupby('scraping_method')['sentiment_score'].agg(['mean', 'std'])
        
        x_pos = range(len(method_sentiment_avg))
        bars = axes[3, 0].bar(x_pos, method_sentiment_avg['mean'], 
                             yerr=method_sentiment_avg['std'], 
                             color=['#3498db', '#e74c3c'][:len(method_sentiment_avg)],
                             capsize=5, alpha=0.7)
        
        axes[3, 0].set_title('Sentiment Analysis: Method Comparison', fontsize=12, fontweight='bold')
        axes[3, 0].set_xlabel('Scraping Method')
        axes[3, 0].set_ylabel('Average Sentiment Score')
        axes[3, 0].set_xticks(x_pos)
        axes[3, 0].set_xticklabels(method_sentiment_avg.index)
        axes[3, 0].axhline(0, color='black', linestyle='-', alpha=0.5)
        
        for i, bar in enumerate(bars):
            height = bar.get_height()
            axes[3, 0].text(bar.get_x() + bar.get_width()/2., height + 0.01,
                           f'{height:.3f}', ha='center', va='bottom', fontsize=10)
    
    if 'scraping_method' in df.columns:
        selenium_sources = ['ap', 'cnn']
        requests_sources = ['bbc', 'guardian']
        
        selenium_success = len([s for s in selenium_sources if s in df['source'].values])
        requests_success = len([s for s in requests_sources if s in df['source'].values])
        
        success_data = ['Selenium', 'Requests']
        success_counts = [selenium_success, requests_success]
        success_rates = [s/2.0 for s in success_counts]
        
        bars = axes[3, 1].bar(success_data, success_rates, color=['#3498db', '#e74c3c'])
        axes[3, 1].set_title('Method Success Rate', fontsize=12, fontweight='bold')
        axes[3, 1].set_ylabel('Success Rate (Sources Working)')
        axes[3, 1].set_ylim(0, 1)
        
        for bar, rate in zip(bars, success_rates):
            height = bar.get_height()
            axes[3, 1].text(bar.get_x() + bar.get_width()/2., height + 0.02,
                           f'{rate:.1%}', ha='center', va='bottom', fontsize=10)
    
    all_keywords = []
    for keywords_str in df['keywords'].dropna():
        try:
            keywords = json.loads(keywords_str)
            all_keywords.extend(keywords)
        except:
            continue
    
    if all_keywords:
        if WORDCLOUD_AVAILABLE:
            keyword_freq = Counter(all_keywords)
            wordcloud = WordCloud(width=400, height=300, background_color='white', 
                                colormap='viridis', max_words=50).generate_from_frequencies(keyword_freq)
            axes[3, 2].imshow(wordcloud, interpolation='bilinear')
            axes[3, 2].axis('off')
            axes[3, 2].set_title('Keywords Cloud', fontsize=12, fontweight='bold')
        else:
            keyword_freq = Counter(all_keywords)
            top_keywords = dict(keyword_freq.most_common(10))
            bars = axes[3, 2].barh(list(top_keywords.keys()), list(top_keywords.values()), 
                                  color='#2ecc71', alpha=0.7)
            axes[3, 2].set_title('Top 10 Keywords', fontsize=12, fontweight='bold')
            axes[3, 2].set_xlabel('Frequency')
    else:
        axes[3, 2].text(0.5, 0.5, 'No keywords available\nRun scraping first', 
                       ha='center', va='center', transform=axes[3, 2].transAxes)
        axes[3, 2].set_title('Keywords Analysis', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig('mixed_method_sentiment_dashboard.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    print("Mixed method dashboard saved as 'mixed_method_sentiment_dashboard.png'")

def export_enhanced_tableau_data():
    conn = sqlite3.connect('enhanced_news_articles.db')
    df = pd.read_sql_query('SELECT * FROM articles ORDER BY scraped_at DESC', conn)
    conn.close()
    
    if len(df) == 0:
        print("No data found. Run mixed method scraping first.")
        return
    
    if not os.path.exists('mixed_method_tableau_data'):
        os.makedirs('mixed_method_tableau_data')
    
    df['sentiment_category'] = df['sentiment_score'].apply(lambda x: 
        "Very Positive" if x >= 0.3 else
        "Positive" if x >= 0.1 else
        "Neutral" if x >= -0.1 else
        "Negative" if x >= -0.3 else
        "Very Negative")
    
    df['content_length'] = df['content'].str.len()
    df['scraped_date'] = pd.to_datetime(df['scraped_at']).dt.date
    df['scraped_hour'] = pd.to_datetime(df['scraped_at']).dt.hour
    df['day_of_week'] = pd.to_datetime(df['scraped_at']).dt.day_name()
    
    region_mapping = {
        'bbc': 'UK/Europe', 'ap': 'International', 'guardian': 'UK/Europe',
        'cnn': 'North America'
    }
    df['region'] = df['source'].map(region_mapping)
    
    selenium_sources = ['ap', 'cnn']
    df['method_category'] = df['source'].apply(
        lambda x: 'Selenium' if x in selenium_sources else 'Requests'
    )
    
    df.to_csv('mixed_method_tableau_data/mixed_method_news_sentiment_data.csv', index=False)
    
    method_comparison = df.groupby(['scraping_method', 'source']).agg({
        'sentiment_score': ['mean', 'std', 'count'],
        'content_length': 'mean'
    }).reset_index()
    method_comparison.columns = ['_'.join(col).strip() for col in method_comparison.columns.values]
    method_comparison.to_csv('mixed_method_tableau_data/method_comparison_data.csv', index=False)
    
    print(f"Mixed Method Tableau datasets exported:")
    print(f"   - mixed_method_news_sentiment_data.csv: {len(df)} rows")
    print(f"   - method_comparison_data.csv: {len(method_comparison)} rows")
    print(f"   - Sources covered: {', '.join(df['source'].unique())}")
    print(f"   - Selenium sources: {len(df[df['method_category'] == 'Selenium']['source'].unique())}")
    print(f"   - Requests sources: {len(df[df['method_category'] == 'Requests']['source'].unique())}")

def generate_enhanced_market_report():
    conn = sqlite3.connect('enhanced_news_articles.db')
    df = pd.read_sql_query('SELECT * FROM articles ORDER BY scraped_at DESC', conn)
    conn.close()
    
    if len(df) == 0:
        print("No data found for market report.")
        return
    
    market_df = df[df['category'].isin(['business', 'technology', 'world'])]
    
    if len(market_df) == 0:
        print("No market-related articles found.")
        return
    
    market_sentiment = market_df['sentiment_score'].mean()
    
    print("MIXED METHOD MARKET SENTIMENT INTELLIGENCE REPORT")
    print(f"Overall Market Sentiment Score: {market_sentiment:.3f}")
    
    classification = (
        "Very Positive" if market_sentiment >= 0.2 else
        "Positive" if market_sentiment >= 0.05 else
        "Neutral" if market_sentiment >= -0.05 else
        "Negative" if market_sentiment >= -0.2 else
        "Very Negative"
    )
    print(f"Classification: {classification}")
    
    print(f"Articles Analyzed: {len(market_df)}")
    print(f"Sources: {', '.join(market_df['source'].unique())}")
    
    if 'scraping_method' in market_df.columns:
        selenium_df = market_df[market_df['scraping_method'] == 'selenium']
        requests_df = market_df[market_df['scraping_method'] == 'requests']
        
        print("METHOD BREAKDOWN:")
        if len(selenium_df) > 0:
            selenium_sentiment = selenium_df['sentiment_score'].mean()
            print(f"   Selenium: {selenium_sentiment:.3f} sentiment ({len(selenium_df)} articles)")
        if len(requests_df) > 0:
            requests_sentiment = requests_df['sentiment_score'].mean()
            print(f"   Requests: {requests_sentiment:.3f} sentiment ({len(requests_df)} articles)")
    
    print("SOURCE BREAKDOWN:")
    selenium_sources = ['ap', 'cnn']
    for source in market_df['source'].unique():
        source_df = market_df[market_df['source'] == source]
        source_sentiment = source_df['sentiment_score'].mean()
        method_name = "Selenium" if source in selenium_sources else "Requests"
        print(f"   {source.upper()} ({method_name}): {source_sentiment:.3f} ({len(source_df)} articles)")
    
    print("CATEGORY BREAKDOWN:")
    for category in market_df['category'].unique():
        cat_df = market_df[market_df['category'] == category]
        cat_sentiment = cat_df['sentiment_score'].mean()
        print(f"   {category.capitalize()}: {cat_sentiment:.3f} ({len(cat_df)} articles)")
    
    interpretation_parts = []
    if market_sentiment >= 0.1:
        interpretation_parts.append("Strong positive market sentiment detected.")
        interpretation_parts.append("Consider bullish market positions.")
    elif market_sentiment <= -0.1:
        interpretation_parts.append("Concerning negative sentiment revealed.")
        interpretation_parts.append("Consider defensive strategies.")
    else:
        interpretation_parts.append("Neutral market sentiment indicated.")
        interpretation_parts.append("Monitor closely for directional signals.")
    
    if 'scraping_method' in market_df.columns and len(selenium_df) > 0 and len(requests_df) > 0:
        if abs(selenium_sentiment - requests_sentiment) > 0.1:
            if selenium_sentiment > requests_sentiment:
                interpretation_parts.append(f"Selenium sources show more positive sentiment ({selenium_sentiment:.3f} vs {requests_sentiment:.3f}).")
            else:
                interpretation_parts.append(f"Requests sources show more positive sentiment ({requests_sentiment:.3f} vs {selenium_sentiment:.3f}).")
        else:
            interpretation_parts.append("Both scraping methods show consistent sentiment readings.")
    
    print("Enhanced Interpretation:")
    for part in interpretation_parts:
        print(f"   {part}")

def main():
    print("MIXED METHOD GLOBAL NEWS SENTIMENT SYSTEM")
    print("Features:")
    print("   Mixed Selenium + Requests approach")
    print("   Enhanced error recovery")
    print("   Method performance comparison")
    print("SELENIUM SOURCES (Dynamic Content):")
    print("   AP, CNN")
    print("REQUESTS SOURCES (Static Content):")
    print("   BBC, Guardian")
    
    while True:
        print("Choose an option:")
        print("1. Mixed method news scraping (Selenium + Requests)")
        print("2. Analyze sentiment with method comparison")
        print("3. Generate mixed method visualizations")
        print("4. Export data for Tableau Public")
        print("5. Market intelligence report")
        print("6. Method performance analysis")
        print("7. Exit")
        
        choice = input("Enter your choice (1-7): ").strip()
        
        if choice == '1':
            print("Starting MIXED METHOD news scraping...")
            
            try:
                scraper = EnhancedNewsScraper(max_articles_per_source=20)
                articles = scraper.scrape_all_sources()
                
                if len(articles) > 0:
                    selenium_count = len([a for a in articles if a.scraping_method == 'selenium'])
                    requests_count = len([a for a in articles if a.scraping_method == 'requests'])
                    
                    print(f"SUCCESS! {len(articles)} articles collected!")
                    print(f"Selenium articles: {selenium_count}")
                    print(f"Requests articles: {requests_count}")
                else:
                    print("No articles collected. Check internet connection and dependencies.")
                    
            except Exception as e:
                print(f"Error during mixed method scraping: {str(e)}")
        
        elif choice == '2':
            print("Analyzing sentiment with method comparison...")
            
            try:
                analyzer = EnhancedSentimentAnalyzer()
                df = analyzer.load_articles()
                
                if len(df) == 0:
                    print("No articles found. Please run mixed method scraping first.")
                    continue
                    
                print(f"MIXED METHOD NEWS ANALYSIS")
                print(f"Total articles: {len(df)}")
                print(f"Sources: {', '.join(df['source'].unique())}")
                print(f"Date range: {df['scraped_at'].min()} to {df['scraped_at'].max()}")
                
                if 'scraping_method' in df.columns:
                    method_counts = df['scraping_method'].value_counts()
                    print("METHOD BREAKDOWN:")
                    for method, count in method_counts.items():
                        percentage = (count / len(df)) * 100
                        print(f"   {method.capitalize()}: {count} articles ({percentage:.1f}%)")
                
                distribution = analyzer.sentiment_distribution()
                print("OVERALL SENTIMENT:")
                for sentiment, count in distribution['overall'].items():
                    percentage = (count / len(df)) * 100
                    print(f"   {sentiment.capitalize()}: {count} ({percentage:.1f}%)")
                
                method_comparison = analyzer.cross_method_comparison()
                if method_comparison:
                    print("METHOD PERFORMANCE COMPARISON:")
                    for method, data in method_comparison.items():
                        print(f"   {method.upper()}:")
                        print(f"      Articles: {data['total_articles']}")
                        print(f"      Avg Sentiment: {data['avg_sentiment']:.3f}")
                        print(f"      Avg Content Length: {data['avg_content_length']:.0f} chars")
                        print(f"      Source Coverage: {data['source_coverage']}/2 ({data['success_rate']:.1%})")
                
                print("SOURCE PERFORMANCE:")
                selenium_sources = ['ap', 'cnn']
                for source in sorted(df['source'].unique()):
                    source_df = df[df['source'] == source]
                    method = "Selenium" if source in selenium_sources else "Requests"
                    avg_sentiment = source_df['sentiment_score'].mean()
                    print(f"   {source.upper()} ({method}): {avg_sentiment:.3f} sentiment ({len(source_df)} articles)")
                
                topics = analyzer.trending_topics()
                if topics:
                    print("TOP 10 TRENDING TOPICS:")
                    for i, (topic, count) in enumerate(topics[:10], 1):
                        print(f"   {i:2d}. {topic} ({count} mentions)")
                        
                analyzer.conn.close()
                
            except Exception as e:
                print(f"Error during analysis: {str(e)}")
                
        elif choice == '3':
            print("Generating mixed method visualizations...")
            try:
                conn = sqlite3.connect('enhanced_news_articles.db')
                df = pd.read_sql_query('SELECT * FROM articles ORDER BY scraped_at DESC', conn)
                conn.close()
                
                if len(df) == 0:
                    print("No articles found. Please run mixed method scraping first.")
                    continue
                
                create_enhanced_dashboard(df)
                
            except Exception as e:
                print(f"Error generating visualizations: {str(e)}")
            
        elif choice == '4':
            print("Exporting mixed method data for Tableau Public...")
            try:
                export_enhanced_tableau_data()
                
            except Exception as e:
                print(f"Error exporting data: {str(e)}")
            
        elif choice == '5':
            print("Generating Mixed Method Market Intelligence Report...")
            try:
                generate_enhanced_market_report()
                
            except Exception as e:
                print(f"Error generating market report: {str(e)}")
        
        elif choice == '6':
            print("Method Performance Analysis...")
            try:
                analyzer = EnhancedSentimentAnalyzer()
                df = analyzer.load_articles()
                
                if len(df) == 0:
                    print("No articles found. Run mixed method scraping first.")
                    continue
                
                method_analysis = analyzer.method_performance_analysis()
                
                print("SCRAPING METHOD PERFORMANCE ANALYSIS")
                
                for method, data in method_analysis.items():
                    print(f"{method.upper()} METHOD:")
                    print(f"   Total Articles: {data['article_count']}")
                    print(f"   Average Content Length: {data['avg_content_length']:.0f} characters")
                    print(f"   Average Sentiment: {data['avg_sentiment']:.3f}")
                    print(f"   Sentiment Consistency: {data['sentiment_std']:.3f}")
                    print(f"   Sources Successfully Scraped: {len(data['sources'])}/2 ({data['success_rate']:.1%})")
                    print(f"   Sources: {', '.join(data['sources'])}")
                
                print("RECOMMENDATIONS:")
                if len(method_analysis) >= 2:
                    methods = list(method_analysis.keys())
                    if method_analysis[methods[0]]['avg_content_length'] > method_analysis[methods[1]]['avg_content_length']:
                        better_content = methods[0]
                    else:
                        better_content = methods[1]
                    
                    if method_analysis[methods[0]]['success_rate'] > method_analysis[methods[1]]['success_rate']:
                        better_success = methods[0]
                    else:
                        better_success = methods[1]
                    
                    print(f"   {better_content.capitalize()} provides better content quality")
                    print(f"   {better_success.capitalize()} has higher success rate")
                    print("   Mixed approach provides best overall coverage")
                
                analyzer.conn.close()
                
            except Exception as e:
                print(f"Error in method performance analysis: {str(e)}")
            
        elif choice == '7':
            print("Thank you for using the Mixed Method News Sentiment System!")
            break
            
        else:
            print("Invalid choice. Please enter a number between 1-7.")

if __name__ == "__main__":
    main()