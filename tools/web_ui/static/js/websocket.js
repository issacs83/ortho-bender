/**
 * WebSocket manager with auto-reconnect.
 */

class StatusWebSocket {
    constructor() {
        this.ws = null;
        this.callbacks = [];
        this.reconnectDelay = 1000;
        this.maxDelay = 10000;
    }

    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}/ws/status`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this.reconnectDelay = 1000;
        };

        this.ws.onmessage = (ev) => {
            try {
                const data = JSON.parse(ev.data);
                this.callbacks.forEach(cb => cb(data));
            } catch (e) { /* ignore parse errors */ }
        };

        this.ws.onclose = () => {
            setTimeout(() => this.connect(), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxDelay);
        };

        this.ws.onerror = () => {
            this.ws.close();
        };
    }

    onMessage(callback) {
        this.callbacks.push(callback);
    }
}

const statusWS = new StatusWebSocket();
