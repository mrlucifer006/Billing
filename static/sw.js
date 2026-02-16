const CACHE_NAME = 'gdc-billing-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/static/style.css',
    'https://cdn.tailwindcss.com',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
    'https://fonts.googleapis.com/icon?family=Material+Icons'
];

// Install Event: Cache Core Assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[Service Worker] Caching core assets');
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

// Activate Event: Clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(keyList.map((key) => {
                if (key !== CACHE_NAME) {
                    console.log('[Service Worker] Removing old cache', key);
                    return caches.delete(key);
                }
            }));
        })
    );
    self.clients.claim();
});

// Fetch Event: Network First, Fallback to Cache
self.addEventListener('fetch', (event) => {
    // Skip cross-origin requests that are not in our asset list (mostly)
    // But we do want to cache the CDNs if we can.
    // For now, let's just try to handle everything with a simple strategy.
    
    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // If valid response, clone and cache it
                if (!response || response.status !== 200 || response.type !== 'basic') {
                    // response.type 'basic' means same-origin. 
                    // cors requests (CDNs) have type 'cors'. We want to cache those too if possible.
                    // So we loosen the check slightly or just cache everything valid.
                }

                const responseToCache = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });

                return response;
            })
            .catch(() => {
                // Network failed, try cache
                console.log('[Service Worker] Network failed, serving from cache:', event.request.url);
                return caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // Fallback for HTML pages (e.g. /verify?token=...) -> maybe serve a generic offline page?
                    // For now, if /verify is cached, it returns that.
                    // Note: /verify?token=... is unique per user. 
                    // Network First strategy will cache the SPECIFIC url.
                    // So if user refreshes the SAME url offline, it works.
                    
                    // If we want a generic offline page, we'd return it here.
                    // return caches.match('/offline.html');
                });
            })
    );
});
