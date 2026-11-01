/* Fixed local equirectangular projection; all dimensions are CSS pixels. */
(function (root) {
    const cosine = Math.cos(10.818333 * Math.PI / 180);
    function normalize(b, width, height) {
        if (!width || !height) return b;
        const lat = (b.minLat + b.maxLat) / 2, lon = (b.minLon + b.maxLon) / 2;
        const dy = b.maxLat - b.minLat, dx = dy * width / height / cosine;
        return {minLat: lat-dy/2, maxLat: lat+dy/2, minLon: lon-dx/2, maxLon: lon+dx/2};
    }
    function zoom(bounds, width, height, x, y, factor, minSpan, maxSpan) {
        const b = normalize(bounds, width, height);
        const dy = b.maxLat-b.minLat, dx = b.maxLon-b.minLon;
        const scale = Math.max(minSpan / Math.min(dx,dy), Math.min(maxSpan / Math.max(dx,dy), factor));
        const fx = x/width, fy = 1-y/height;
        const lat = b.minLat+fy*dy, lon = b.minLon+fx*dx;
        return {minLat:lat-fy*dy*scale, maxLat:lat+(1-fy)*dy*scale,
            minLon:lon-fx*dx*scale, maxLon:lon+(1-fx)*dx*scale};
    }
    const api = {normalize, zoom};
    if (typeof module !== 'undefined') module.exports = api;
    else root.AstraRadarGeometry = api;
})(typeof window === 'undefined' ? globalThis : window);
