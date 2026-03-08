/**
 * 2D SVG wire shape preview from B-code steps.
 * Renders top-down (XY) projection of the wire.
 */

function renderWirePreview(svgElement, steps) {
    if (!svgElement || !steps || steps.length === 0) {
        svgElement.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#666">No steps</text>';
        return;
    }

    const points = [];
    let x = 0, y = 0;
    let angle = 0; // current direction in radians

    points.push({ x, y });

    for (const step of steps) {
        // Feed: advance along current direction
        const L = step.L_mm || 0;
        x += L * Math.cos(angle);
        y += L * Math.sin(angle);
        points.push({ x, y });

        // Bend: change direction
        const theta = (step.theta_compensated_deg || step.theta_deg || 0) * Math.PI / 180;
        angle += theta;
    }

    // Compute bounding box
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const p of points) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
    }

    const pad = 20;
    const w = svgElement.clientWidth || 400;
    const h = svgElement.clientHeight || 300;
    const rangeX = (maxX - minX) || 1;
    const rangeY = (maxY - minY) || 1;
    const scale = Math.min((w - 2 * pad) / rangeX, (h - 2 * pad) / rangeY);

    function tx(px) { return pad + (px - minX) * scale; }
    function ty(py) { return h - pad - (py - minY) * scale; }

    let pathD = `M ${tx(points[0].x)} ${ty(points[0].y)}`;
    for (let i = 1; i < points.length; i++) {
        pathD += ` L ${tx(points[i].x)} ${ty(points[i].y)}`;
    }

    svgElement.innerHTML = `
        <path d="${pathD}" fill="none" stroke="#00d4ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="${tx(points[0].x)}" cy="${ty(points[0].y)}" r="4" fill="#00e676"/>
        <circle cx="${tx(points[points.length-1].x)}" cy="${ty(points[points.length-1].y)}" r="4" fill="#ff5252"/>
    `;
}
