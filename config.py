# Telegram API Credentials
API_ID = "28320430"
API_HASH = "2a15fdaf244a9f3ec4af7ce0501f9db8"
BOT_TOKEN = "7894481490:AAEUc8oiRhNgMEjSytgXKAYvolmznxJM9n0"

# Channel Configuration
INVITE_LINK = "zr6kLxcG7TQ5NGU9"  # Invite link tanpa 'https://t.me/+'
CHANNEL_ID = "-1002443114227"  # Channel ID dalam format numerik

# Reserved Telegram usernames that cannot be registered
RESERVED_WORDS = {
    # Official Telegram terms
    'telegram', 'admin', 'support', 'security', 'settings', 'contacts',
    'chat', 'group', 'channel', 'bot', 'test', 'null', 'undefined',
    'official', 'help', 'info', 'news', 'store', 'contact',

    # Technical terms
    'system', 'api', 'app', 'dev', 'root', 'admin', 'mod', 'moderator',
    'database', 'server', 'client', 'web', 'mobile', 'desktop', 'user',
    'account', 'profile', 'login', 'logout', 'register', 'signup', 'signin',

    # Support related
    'helpdesk', 'support', 'assistance', 'service', 'customer', 'care',
    'feedback', 'contact', 'report', 'issue', 'problem', 'inquiry', 
    'question', 'answer', 'faq', 'team', 'staff', 'operator', 'agent',

    # Sensitive terms
    'verify', 'verification', 'confirmed', 'authentic', 'official', 'real',
    'true', 'genuine', 'original', 'legitimate', 'auth', 'authenticated',
    'security', 'secure', 'protected', 'safe', 'privacy', 'private',

    # Financial terms 
    'payment', 'wallet', 'money', 'cash', 'crypto', 'bitcoin', 'finance',
    'bank', 'premium', 'pay', 'purchase', 'buy', 'sell', 'price', 'cost',

    # Social media companies
    'facebook', 'meta', 'instagram', 'whatsapp', 'twitter', 'tiktok',
    'youtube', 'google', 'microsoft', 'apple', 'amazon', 'netflix',
    'spotify', 'paypal', 'visa', 'mastercard', 'snapchat', 'reddit',

    # Common spam terms
    'porn', 'adult', 'xxx', 'sex', 'hack', 'crack', 'cheat', 'spam',
    'free', 'offer', 'discount', 'deal', 'promo', 'promotion', 'winner',
    'prize', 'limited', 'hurry'
}