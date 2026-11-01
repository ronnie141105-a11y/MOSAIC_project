/**
 * ASTRA pluggable geographic overlay layers.
 *
 * Loads `geo/manifest.json` (a list of named layers: FIRs, sectors,
 * airways, waypoints, airports, coastlines) plus each layer's GeoJSON
 * file, and draws them onto any canvas 2D context given a lat/lon ->
 * pixel `project(lat, lon) -> [x, y]` function.
 *
 * This module has NO geographic knowledge baked in -- no coordinates,
 * no country/FIR names, nothing. Every layer file starts out an empty
 * `FeatureCollection`; converting the Vietnam AIP into these files
 * later is the *only* step needed to put real geometry on the map. If
 * you are looking for where Vietnam's FIR/sector polygons should go,
 * it is `geo/firs.json` / `geo/sectors.json`, not this file.
 *
 * Used by both the Operations map and (once built) the Dissipation
 * Workspace's Traffic Projection Display -- one shared instance,
 * created once in `dashboard.js`, so geo overlays are never drawn by
 * two different code paths.
 */

class GeoLayerManager {
    /**
     * @param {string} manifestUrl - Path to the layer manifest JSON.
     */
    constructor(manifestUrl) {
        this.manifestUrl = manifestUrl || "/static/geo/manifest.json";
        this.layers = []; // [{id, label, kind, style, labelField, zIndex, visible, geojson}]
        this.ready = false;
    }

    /** Fetch the manifest and every layer file it references. Safe to call once. */
    async init() {
        try {
            const manifestResponse = await fetch(this.manifestUrl);
            const manifest = await manifestResponse.json();
            const base = this.manifestUrl.replace(/manifest\.json$/, "");
            const entries = await Promise.all(
                (manifest.layers || []).map(async (entry) => {
                    let geojson = { type: "FeatureCollection", features: [] };
                    try {
                        const response = await fetch(entry.file.startsWith('/') ? entry.file : base + entry.file.replace(/^geo\//, ""));
                        geojson = await response.json();
                    } catch (err) {
                        console.warn(`GeoLayerManager: could not load layer '${entry.id}' (${entry.file}); drawing it empty.`, err);
                    }
                    return {
                        id: entry.id,
                        label: entry.label,
                        kind: entry.kind,
                        style: entry.style || {},
                        labelField: entry.label_field || null,
                        zIndex: entry.z_index || 0,
                        visible: entry.default_visible !== false,
                        toggleable: entry.toggleable !== false,
                        toggleSection: entry.toggle_section || null,
                        //: When set, this layer shares one toggle checkbox
                        //: with every other layer using the same group id
                        //: (e.g. "Coastlines" + "Country borders" -> one
                        //: "Coastlines & borders" checkbox) -- see
                        //: getToggleList()/setVisible() below. Undefined
                        //: for layers that get their own individual toggle.
                        toggleGroup: entry.toggle_group || null,
                        toggleLabel: entry.toggle_label || entry.label,
                        geojson,
                    };
                })
            );
            this.layers = entries.sort((a, b) => a.zIndex - b.zIndex);
        } catch (err) {
            console.warn("GeoLayerManager: manifest failed to load; map will render with no geo overlays.", err);
            this.layers = [];
        }
        this.ready = true;
        return this.layers;
    }

    /** `[{id, label, kind, visible}]` for a layer-toggle control. Layers
     * sharing a `toggleGroup` collapse into a single entry (keyed by the
     * group id, labelled with the group's `toggleLabel`) so e.g.
     * "Coastlines" and "Country borders" show as one checkbox. */
    getToggleList() {
        const seenGroups = new Set();
        const list = [];
        this.layers.forEach((l) => {
            if (l.toggleable === false) return;
            if (l.toggleGroup) {
                if (seenGroups.has(l.toggleGroup)) {
                    return;
                }
                seenGroups.add(l.toggleGroup);
                list.push({ id: l.toggleGroup, label: l.toggleLabel, kind: l.kind, visible: l.visible, section: l.toggleSection });
                return;
            }
            list.push({ id: l.id, label: l.label, kind: l.kind, visible: l.visible, section: l.toggleSection });
        });
        return list;
    }

    /** Sets visibility for one layer, or -- if `id` names a toggle group
     * rather than an individual layer id -- every layer in that group. */
    setVisible(id, visible) {
        let matched = false;
        this.layers.forEach((l) => {
            if (l.toggleable !== false && (l.id === id || l.toggleGroup === id)) {
                l.visible = visible;
                matched = true;
            }
        });
        return matched;
    }

    isEmpty() {
        return this.layers.every((l) => (l.geojson.features || []).length === 0);
    }

    /**
     * Draw every visible layer, in ascending z-index order, onto `ctx`.
     *
     * @param {CanvasRenderingContext2D} ctx
     * @param {(lat: number, lon: number) => [number, number]} project
     * @param {(layer: object, feature: object) => boolean} [featureFilter] -
     *   optional per-feature predicate (e.g. hide one named sector while
     *   the "sectors" layer as a whole stays visible). Defaults to "draw
     *   everything in every visible layer".
     */
    draw(ctx, project, featureFilter) {
        // Label decluttering: one shared registry of already-placed label
        // boxes for this whole draw pass (across every layer, not just
        // within one) -- a waypoint label and a sector label are both
        // just "text on the map" competing for the same screen space.
        // Greedy "skip if it would overlap something already placed"; the
        // marker/line itself is never skipped, only its text label.
        this._labelRects = [];
        this._priorityPointLabels = new Set();
        // Reserve important point labels before ordinary navigation labels.
        this.layers.filter(l=>l.visible&&l.style.label_priority).forEach(layer=>{
            ctx.font=`${layer.style.label_size||9}px monospace`;
            (layer.geojson.features||[]).filter(f=>f.geometry?.type==='Point').forEach(f=>{
                const label=f.properties?.[layer.labelField];if(!label)return;
                this._priorityPointLabels.add(label);
                const pos=this._pointLabelPosition(project,layer.style,f.geometry.coordinates);
                const width=ctx.measureText(label).width;
                this._reserveLabelSpace(pos.x-(pos.align==='right'?width:0),pos.y,width,layer.style.label_size||9);
            });
        });
        this.layers.forEach((layer) => {
            if (!layer.visible) {
                return;
            }
            const features = layer.geojson.features || [];
            features.forEach((feature) => {
                if (featureFilter && !featureFilter(layer, feature)) {
                    return;
                }
                this._drawFeature(ctx, project, layer, feature);
            });
        });
    }

    _drawFeature(ctx, project, layer, feature) {
        const geometry = feature.geometry;
        if (!geometry) {
            return;
        }
        let label = layer.labelField ? feature.properties && feature.properties[layer.labelField] : null;
        if(!this._protectedNavNames)this._protectedNavNames=new Set(this.layers.filter(l=>['navaids','airports'].includes(l.id)).flatMap(l=>(l.geojson?.features||[]).flatMap(f=>[f.properties?.ident,f.properties?.icao,f.properties?.name])).filter(Boolean));
        if(window.MOSAIC_CONTROL_VIEW==='centre' && this.hideWaypointNames && !this._protectedNavNames.has(label) && geometry.type==='Point' &&
            !['vor','vor_dme','ndb','airport'].includes(feature.properties?.symbol||layer.style.marker) && !['vor','vor_dme','ndb','airport','aerodrome','navaid'].includes(feature.properties?.category) && !['navaids','airports'].includes(layer.id))label=null;
        if(geometry.type==='Point'&&!layer.style.label_priority&&this._priorityPointLabels?.has(label))label=null;
        switch (geometry.type) {
            case "Polygon":
                this._drawPolygon(ctx, project, layer.style, geometry.coordinates, label);
                break;
            case "MultiPolygon":
                geometry.coordinates.forEach((poly) => this._drawPolygon(ctx, project, layer.style, poly, label));
                break;
            case "LineString":
                this._drawLine(ctx, project, layer.style, geometry.coordinates, label);
                break;
            case "MultiLineString":
                geometry.coordinates.forEach((line) => this._drawLine(ctx, project, layer.style, line, label));
                break;
            case "Point":
                this._drawPoint(ctx, project, layer.style.marker==='navaid' ? {...layer.style, marker:feature.properties.symbol || 'star', compassRose:feature.properties.compass_rose} : layer.style, geometry.coordinates, label);
                break;
            case "MultiPoint":
                geometry.coordinates.forEach((pt) => this._drawPoint(ctx, project, layer.style, pt, label));
                break;
            default:
                break; // Unsupported geometry kind: draw nothing rather than guess.
        }
    }

    /** Would a label box at (x, y) sized (w, h) overlap one already placed
     * this draw pass? If not, reserve it and return true (caller may draw). */
    _reserveLabelSpace(x, y, w, h) {
        const pad = 2;
        const box = { x1: x - pad, y1: y - h - pad, x2: x + w + pad, y2: y + pad };
        const overlaps = this._labelRects.some(
            (r) => box.x1 < r.x2 && box.x2 > r.x1 && box.y1 < r.y2 && box.y2 > r.y1
        );
        if (overlaps) {
            return false;
        }
        this._labelRects.push(box);
        return true;
    }

    /** Draw `text` at (x, y) (baseline-left) if it doesn't collide with an
     * already-placed label this pass; always a no-op on the marker/line
     * itself, only ever skips the *text*. */
    _drawDeclutteredLabel(ctx, text, x, y) {
        const width = ctx.measureText(text).width;
        if (!this._reserveLabelSpace(x, y, width, 10)) {
            return;
        }
        ctx.fillText(text, x, y);
    }

    /** Area-weighted centroid of a closed polygon ring (shoelace formula) --
     * a far better label anchor than "first vertex," which tends to land
     * on a boundary corner rather than inside the shape. */
    _ringCentroid(ring) {
        let area = 0;
        let cx = 0;
        let cy = 0;
        for (let i = 0; i < ring.length - 1; i++) {
            const [x0, y0] = ring[i];
            const [x1, y1] = ring[i + 1];
            const cross = x0 * y1 - x1 * y0;
            area += cross;
            cx += (x0 + x1) * cross;
            cy += (y0 + y1) * cross;
        }
        area *= 0.5;
        if (Math.abs(area) < 1e-9) {
            // Degenerate ring (all points ~collinear) -- fall back to a
            // simple vertex average rather than dividing by ~0.
            const n = ring.length - 1 || 1;
            const sum = ring.slice(0, -1).reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]);
            return [sum[0] / n, sum[1] / n];
        }
        return [cx / (6 * area), cy / (6 * area)];
    }
    _drawPolygon(ctx, project, style, rings, label) {
        if (!rings || rings.length === 0) {
            return;
        }
        ctx.beginPath();
        rings.forEach((ring) => {
            ring.forEach(([lon, lat], idx) => {
                const [x, y] = project(lat, lon);
                if (idx === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            });
            ctx.closePath();
        });
        if (style.fill) {
            ctx.fillStyle = style.fill;
            ctx.fill();
        }
        ctx.setLineDash(style.dash || []);
        ctx.strokeStyle = style.stroke || "#4a5866";
        ctx.lineWidth = style.width || 1;
        ctx.stroke();
        ctx.setLineDash([]);
        if (label) {
            const [clon, clat] = this._ringCentroid(rings[0]);
            const [lx, ly] = project(clat, clon);
            ctx.fillStyle = style.stroke || "#8494a2";
            ctx.font = "10px monospace";
            this._drawDeclutteredLabel(ctx, label, lx - ctx.measureText(label).width / 2, ly);
        }
    }

    _drawLine(ctx, project, style, points, label) {
        if (!points || points.length === 0) {
            return;
        }
        ctx.beginPath();
        points.forEach(([lon, lat], idx) => {
            const [x, y] = project(lat, lon);
            if (idx === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.setLineDash(style.dash || []);
        ctx.strokeStyle = style.stroke || "#33424e";
        ctx.lineWidth = style.width || 1;
        ctx.stroke();
        ctx.setLineDash([]);

        if (label) {
            const mid = points[Math.floor(points.length / 2)];
            const [mx, my] = project(mid[1], mid[0]);
            ctx.fillStyle = style.stroke || "#8494a2";
            ctx.font = "9px monospace";
            this._drawDeclutteredLabel(ctx, label, mx + 3, my - 3);
        }
    }

    _pointLabelPosition(project,style,coord) {
        const [x,y]=project(coord[1],coord[0]);
        const centre=style.label_radial_center;
        const left=centre&&x<project(centre[1],centre[0])[0];
        return {x:x+(left?-1:1)*((style.size||3)+3),y:y+3,align:left?'right':'left'};
    }

    _drawPoint(ctx, project, style, coord, label) {
        const [lon, lat] = coord;
        const [x, y] = project(lat, lon);
        const size = style.size || 3;
        if(style.halo){ctx.save();ctx.beginPath();ctx.arc(x,y,size+3,0,Math.PI*2);ctx.strokeStyle=style.stroke||style.fill;ctx.globalAlpha=.45;ctx.lineWidth=1;ctx.stroke();ctx.restore();}
        ctx.fillStyle = style.fill || "#d7e2ea";
        if(style.compassRose)this._drawCompassRose(ctx,x,y,style.stroke);
        switch (style.marker) {
            case "vor": case "vor_dme": case "ndb":
                this._drawNavaid(ctx,x,y,size,style.marker,style.stroke);
                break;
            case "star":
                this._drawStar(ctx, x, y, size);
                break;
            case "triangle":
                ctx.beginPath();
                ctx.moveTo(x, y - size * 1.2);
                ctx.lineTo(x + size, y + size);
                ctx.lineTo(x - size, y + size);
                ctx.closePath();
                ctx.fill();
                break;
            case "square":
                ctx.fillRect(x - size, y - size, size * 2, size * 2);
                break;
            case "diamond":
                ctx.beginPath();
                ctx.moveTo(x, y - size);
                ctx.lineTo(x + size, y);
                ctx.lineTo(x, y + size);
                ctx.lineTo(x - size, y);
                ctx.closePath();
                ctx.fill();
                break;
            default:
                ctx.beginPath();
                ctx.arc(x, y, size, 0, Math.PI * 2);
                ctx.fill();
                break;
        }
        if (label) {
            ctx.save();
            ctx.fillStyle = style.fill || "#8494a2";
            ctx.font = `${style.label_size||9}px monospace`;
            const pos=this._pointLabelPosition(project,style,coord);
            ctx.textAlign=pos.align;
            if(style.label_priority){
                if(style.label_halo){ctx.save();ctx.strokeStyle=style.label_halo;ctx.lineWidth=3;ctx.strokeText(label,pos.x,pos.y);ctx.restore();}
                ctx.fillText(label,pos.x,pos.y);
            }else this._drawDeclutteredLabel(ctx, label, pos.x, pos.y);
            ctx.restore();
        }
    }

    _drawNavaid(ctx,x,y,size,kind,color) {
        ctx.save();ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.2;ctx.setLineDash([]);
        if(kind==='ndb') {
            for(const radius of [size*.8,size*1.4]) {
                const count=radius===size*.8?12:20;
                for(let i=0;i<count;i++) {
                    const a=i*2*Math.PI/count;
                    ctx.beginPath();ctx.arc(x+Math.cos(a)*radius,y+Math.sin(a)*radius,.65,0,Math.PI*2);ctx.fill();
                }
            }
        } else {
            ctx.beginPath();
            for(let i=0;i<6;i++) {
                const a=i*Math.PI/3;
                const px=x+Math.cos(a)*size,py=y+Math.sin(a)*size;
                if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);
            }
            ctx.closePath();ctx.stroke();
            if(kind==='vor_dme')ctx.strokeRect(x-size-1,y-size-1,2*size+2,2*size+2);
        }
        ctx.beginPath();ctx.arc(x,y,1.5,0,Math.PI*2);ctx.fill();ctx.restore();
    }

    _drawCompassRose(ctx,x,y,color) {
        ctx.save();ctx.translate(x,y);
        // Reference charts specify variation 1 degree west: magnetic north is left of true north.
        ctx.rotate(-Math.PI/180);ctx.strokeStyle='#70aebc';ctx.fillStyle='#70aebc';ctx.globalAlpha=.7;ctx.lineWidth=.8;
        const radius=24; // Fixed CSS pixels, independent of the geographic zoom.
        ctx.beginPath();ctx.arc(0,0,radius,0,Math.PI*2);ctx.stroke();
        for(let deg=0;deg<360;deg+=10) {
            const a=deg*Math.PI/180,inner=radius-(deg%90===0?5:deg%30===0?3:1.5);
            ctx.beginPath();ctx.moveTo(Math.sin(a)*inner,-Math.cos(a)*inner);
            ctx.lineTo(Math.sin(a)*radius,-Math.cos(a)*radius);ctx.stroke();
        }
        ctx.font='8px monospace';ctx.textAlign='center';ctx.textBaseline='middle';
        [['0',0,-18],['9',18,0],['18',0,18],['27',-18,0]].forEach(([label,dx,dy])=>ctx.fillText(label,dx,dy));
        ctx.restore();
    }

    _drawStar(ctx, cx, cy, size) {
        const spikes = 5;
        const outer = size;
        const inner = size / 2.2;
        ctx.beginPath();
        for (let i = 0; i < spikes * 2; i++) {
            const r = i % 2 === 0 ? outer : inner;
            const angle = (Math.PI / spikes) * i - Math.PI / 2;
            const x = cx + r * Math.cos(angle);
            const y = cy + r * Math.sin(angle);
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }
        ctx.closePath();
        ctx.fill();
    }
}

window.GeoLayerManager = GeoLayerManager;
