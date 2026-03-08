/**
 * REST API client wrapper for ortho-bender web dashboard.
 */

async function apiCall(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    return res.json();
}

const API = {
    connect: (port, baudrate = 19200) => apiCall('POST', '/api/connect', { port, baudrate }),
    disconnect: () => apiCall('POST', '/api/disconnect'),
    status: () => apiCall('GET', '/api/status'),

    motorJog: (name, direction, steps, speed = 1000) =>
        apiCall('POST', `/api/motor/${name}/jog`, { direction, steps, speed }),
    motorMoveAbs: (name, direction, steps, speed = 1000) =>
        apiCall('POST', `/api/motor/${name}/move_abs`, { direction, steps, speed }),
    motorInit: (name) => apiCall('POST', `/api/motor/${name}/init`, {}),
    motorStop: (name) => apiCall('POST', `/api/motor/${name}/stop`),
    motorPosition: (name) => apiCall('GET', `/api/motor/${name}/position`),
    stopAll: () => apiCall('POST', '/api/motor/stop_all'),
    initAll: () => apiCall('POST', '/api/motor/init_all'),
    sensors: () => apiCall('GET', '/api/motor/sensors'),

    bcodeValidate: (seq) => apiCall('POST', '/api/bcode/validate', seq),
    bcodeCompensate: (seq) => apiCall('POST', '/api/bcode/compensate', seq),
    bcodeExecute: (seq) => apiCall('POST', '/api/bcode/execute', seq),
    bcodeStop: () => apiCall('POST', '/api/bcode/stop'),
    bcodeState: () => apiCall('GET', '/api/bcode/execution_state'),
    materials: () => apiCall('GET', '/api/bcode/materials'),
};
