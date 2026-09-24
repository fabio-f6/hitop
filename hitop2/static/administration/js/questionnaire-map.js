(() => {
    "use strict";
    const root = document.querySelector("[data-questionnaire-map]");
    if (!root) return;

    const data = JSON.parse(document.getElementById("questionnaire-map-data").textContent);
    const treeElement = root.querySelector("[data-tree]");
    const emptyElement = root.querySelector("[data-empty]");
    const detailsElement = root.querySelector("[data-details]");
    const searchInput = root.querySelector("#questionnaire-map-search");
    const searchResults = root.querySelector("[data-search-results]");
    const visualContainer = root.querySelector("[data-visual-map]");
    const expanded = new Set();
    const nodes = new Map();
    let selectedId = null;
    let currentFilter = "all";
    const spectrumColors = ["#27688f", "#3f785f", "#725b98", "#9a672c", "#2f7880", "#875b72", "#536e9d", "#68782f"];

    function flatten(node, parentId = null, spectrumIndex = 0) {
        node.parentId = parentId;
        node.spectrumIndex = spectrumIndex;
        nodes.set(node.id, node);
        node.children.forEach(child => flatten(child, node.id, spectrumIndex));
    }
    data.roots.forEach((node, index) => flatten(node, null, index));

    function nodeColor(node) {
        return spectrumColors[node.spectrumIndex % spectrumColors.length];
    }

    function questionCountLabel(count) {
        return `${count} ${count === 1 ? "pergunta" : "perguntas"}`;
    }

    function visibleForFilter(node) {
        if (currentFilter === "all") return true;
        if (currentFilter === "problems") return node.has_problem_in_branch;
        if (node.issues.length) return false;
        return node.children.length === 0 || node.children.some(visibleForFilter);
    }

    function renderTree() {
        treeElement.replaceChildren();
        const roots = data.roots.filter(visibleForFilter);
        roots.forEach(node => treeElement.appendChild(renderTreeList(node)));
        const isEmpty = roots.length === 0;
        treeElement.hidden = isEmpty;
        emptyElement.hidden = !isEmpty;
        highlightTreeSelection();
    }

    function renderTreeList(node) {
        const list = document.createElement("ul");
        list.className = "map-tree-list";
        list.setAttribute("role", node.parentId ? "group" : "tree");
        const item = document.createElement("li");
        item.className = `map-tree-node map-${node.type}`;
        item.dataset.nodeId = node.id;
        item.setAttribute("role", "treeitem");
        item.setAttribute("aria-expanded", node.children.length ? String(expanded.has(node.id)) : "false");
        const row = document.createElement("div");
        row.className = "map-node-row";
        row.style.setProperty("--node-color", nodeColor(node));
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "map-toggle";
        toggle.disabled = node.children.length === 0;
        toggle.setAttribute("aria-label", `${expanded.has(node.id) ? "Recolher" : "Expandir"} ${node.label || node.name}`);
        toggle.setAttribute("aria-expanded", String(expanded.has(node.id)));
        toggle.textContent = expanded.has(node.id) ? "▾" : "▸";
        toggle.addEventListener("click", () => toggleTreeNode(node.id));
        const select = document.createElement("button");
        select.type = "button";
        select.className = "map-node-select";
        select.dataset.selectNode = node.id;
        select.setAttribute("aria-label", `Selecionar ${node.type_label} ${node.label || node.name}`);
        const name = document.createElement("span");
        name.className = "map-node-name";
        name.textContent = node.label || node.name;
        const meta = document.createElement("span");
        meta.className = "map-node-meta";
        if (node.type !== "question") {
            const count = document.createElement("span");
            count.textContent = questionCountLabel(node.question_count);
            meta.appendChild(count);
        }
        if (node.issues.length) {
            const warning = document.createElement("span");
            warning.className = "map-problem";
            warning.textContent = "Aviso";
            warning.setAttribute("aria-label", `${node.issues.length} problema estrutural`);
            meta.appendChild(warning);
        }
        select.append(name, meta);
        select.addEventListener("click", () => selectNode(node.id));
        row.append(toggle, select);
        item.appendChild(row);
        if (node.children.length && expanded.has(node.id)) {
            const children = document.createElement("ul");
            children.className = "map-tree-list";
            children.setAttribute("role", "group");
            node.children.filter(visibleForFilter).forEach(child => {
                const childList = renderTreeList(child);
                children.append(...childList.children);
            });
            item.appendChild(children);
        }
        list.appendChild(item);
        return list;
    }

    function toggleTreeNode(id) {
        expanded.has(id) ? expanded.delete(id) : expanded.add(id);
        renderTree();
    }

    function expandTreeAncestors(node) {
        let current = node;
        while (current && current.parentId) {
            expanded.add(current.parentId);
            current = nodes.get(current.parentId);
        }
    }

    function selectNode(id, options = {}) {
        const node = nodes.get(id);
        if (!node) return;
        const expansionChanged = radialMap.syncExpansionForSelection(node, options.toggleScale === true);
        selectedId = id;
        expandTreeAncestors(node);
        const structureChanged = options.structureChanged || expansionChanged;
        renderTree();
        renderDetails(node);
        structureChanged ? radialMap.update() : radialMap.refreshSelection();
        if (options.focusTree !== false) {
            requestAnimationFrame(() => {
                const target = treeElement.querySelector(`[data-select-node="${CSS.escape(id)}"]`);
                if (target) {
                    target.scrollIntoView({ behavior: "smooth", block: "center" });
                    target.focus({ preventScroll: true });
                }
            });
        }
        if (radialMap.isVisible() && options.focusVisual !== false) radialMap.focusNode(id);
    }

    function renderDefaultDetails() {
        detailsElement.replaceChildren();
        const heading = document.createElement("h2");
        heading.className = "h5 fw-bold";
        heading.textContent = "Detalhes";
        const message = document.createElement("p");
        message.className = "text-secondary mb-0";
        message.textContent = "Selecione um elemento da hierarquia ou do mapa.";
        detailsElement.append(heading, message);
    }

    function clearSelection({ collapseExpansions = false } = {}) {
        const structureChanged = collapseExpansions && radialMap.collapseAll();
        selectedId = null;
        highlightTreeSelection();
        renderDefaultDetails();
        structureChanged ? radialMap.update() : radialMap.refreshSelection();
    }

    function highlightTreeSelection() {
        const selected = nodes.get(selectedId);
        const pathIds = new Set(selected ? selected.path.map(part => part.id) : []);
        treeElement.querySelectorAll(".map-node-row").forEach(row => {
            const id = row.parentElement.dataset.nodeId;
            row.classList.toggle("is-selected", id === selectedId);
            row.classList.toggle("is-path", pathIds.has(id) && id !== selectedId);
        });
    }

    function renderDetails(node) {
        detailsElement.replaceChildren();
        const heading = document.createElement("h2");
        heading.className = "h5 fw-bold mb-2";
        heading.textContent = node.label || node.name;
        const breadcrumb = document.createElement("nav");
        breadcrumb.className = "map-breadcrumb";
        breadcrumb.setAttribute("aria-label", "Caminho completo");
        node.path.forEach((part, index) => {
            if (index) breadcrumb.append(" → ");
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = part.label || part.name;
            button.addEventListener("click", () => selectNode(part.id));
            breadcrumb.appendChild(button);
        });
        const dl = document.createElement("dl");
        const fields = [["Tipo", node.type_label]];
        node.path.slice(0, -1).forEach(part => fields.push([nodes.get(part.id).type_label, part.label || part.name]));
        if (node.type !== "question") fields.push(["Perguntas", String(node.question_count)]);
        if (node.type === "question") {
            fields.push(["Texto", node.details.question_text || "Sem texto"]);
            fields.push(["Verificação de atenção", node.details.is_attention_check ? "Sim" : "Não"]);
            if (node.details.is_attention_check) fields.push(["Resposta esperada", node.details.expected_answer || "Não definida"]);
        }
        fields.push(["Estado", node.issues.length ? "Requer atenção" : "Sem problemas detetados"]);
        fields.forEach(([label, value]) => {
            const row = document.createElement("div");
            const dt = document.createElement("dt");
            const dd = document.createElement("dd");
            dt.textContent = label;
            dd.textContent = value;
            row.append(dt, dd);
            dl.appendChild(row);
        });
        detailsElement.append(heading, breadcrumb, dl);
        if (node.issues.length) {
            const issues = document.createElement("div");
            issues.className = "map-issues";
            const title = document.createElement("h3");
            title.className = "h6 fw-bold";
            title.textContent = "Problemas";
            issues.appendChild(title);
            node.issues.forEach(issue => {
                const item = document.createElement("div");
                item.className = "map-issue";
                const strong = document.createElement("strong");
                const description = document.createElement("div");
                strong.textContent = issue.title;
                description.textContent = issue.description;
                item.append(strong, description);
                issues.appendChild(item);
            });
            detailsElement.appendChild(issues);
        }
    }

    function normalized(value) {
        return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-PT");
    }

    function search() {
        const query = normalized(searchInput.value.trim());
        searchResults.replaceChildren();
        if (!query) {
            searchResults.hidden = true;
            return;
        }
        const matches = [...nodes.values()].filter(node => normalized(`${node.name} ${node.label || ""} ${node.details.item_code || ""} ${node.details.question_text || ""}`).includes(query)).slice(0, 30);
        matches.forEach(node => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "map-search-result";
            const label = document.createElement("strong");
            const path = document.createElement("small");
            label.textContent = `${node.label || node.name} · ${node.type_label}`;
            path.textContent = node.display_path_text || node.path_text;
            button.append(label, path);
            button.addEventListener("click", () => {
                searchResults.hidden = true;
                const visualIsActive = root.querySelector("#visual-tab").classList.contains("active");
                selectNode(node.id, { focusTree: !visualIsActive, focusVisual: visualIsActive });
            });
            searchResults.appendChild(button);
        });
        if (!matches.length) {
            const message = document.createElement("div");
            message.className = "p-3 text-secondary";
            message.textContent = "Sem resultados.";
            searchResults.appendChild(message);
        }
        searchResults.hidden = false;
    }

    function createRadialMap() {
        if (!window.d3) throw new Error("D3.js não foi carregado.");
        const d3 = window.d3;
        const svg = d3.select(visualContainer).select("svg");
        const viewport = svg.select("[data-visual-viewport]");
        const linksLayer = viewport.select("[data-visual-links]");
        const nodesLayer = viewport.select("[data-visual-nodes]");
        const tooltip = d3.select(root).select("[data-visual-tooltip]");
        const openScales = new Set();
        const positions = new Map();
        let width = 900;
        let height = 650;
        let firstVisibleRender = true;
        let currentZoom = d3.zoomIdentity;

        const zoom = d3.zoom().scaleExtent([0.35, 4]).clickDistance(4).on("zoom", event => {
            currentZoom = event.transform;
            viewport.attr("transform", currentZoom);
            visualContainer.classList.toggle("show-scale-labels", currentZoom.k >= 0.72);
            visualContainer.classList.toggle("show-question-labels", currentZoom.k >= 2.1);
        });
        svg.call(zoom).on("dblclick.zoom", null);
        svg.on("click.selection-reset", event => {
            if (event.target === svg.node()) clearSelection({ collapseExpansions: true });
        });

        function visualChildren(node) {
            if (node.type === "scale" && !openScales.has(node.id)) return [];
            return node.children.filter(visibleForFilter);
        }

        function hierarchyData() {
            return { id: "visual-root", name: "HiTOP", label: "HiTOP", type: "root", type_label: "Estrutura", children: data.roots.filter(visibleForFilter), issues: [], question_count: data.totals.question_count };
        }

        function spectrumNode(datum) {
            if (datum.data.type === "spectrum") return datum.data;
            const ancestor = datum.ancestors().find(item => item.data.type === "spectrum");
            return ancestor ? ancestor.data : null;
        }

        function colorFor(datum) {
            const spectrum = spectrumNode(datum);
            return spectrum ? nodeColor(spectrum) : "#386f91";
        }

        function fillFor(datum) {
            const base = d3.color(colorFor(datum));
            const lightness = { spectrum: 0.18, subfactor: 0.42, scale: 0.66, question: 0.82 };
            return base ? d3.interpolateRgb(base.formatHex(), "#ffffff")(lightness[datum.data.type] ?? 0.35) : "#dceaf3";
        }

        function radiusFor(datum) {
            return { root: 13, spectrum: 11, subfactor: 8, scale: 6.5, question: 3.8 }[datum.data.type] || 5;
        }

        function estimatedLabelWidth(datum) {
            const label = datum.data.label || datum.data.name;
            if (datum.data.type === "question") return Math.max(48, label.length * 6.2);
            return Math.min(210, Math.max(58, label.length * 6.4));
        }

        function visibleLabel(datum) {
            const label = datum.data.label || datum.data.name;
            if (datum.data.type !== "scale") return label;
            return label.length > 30 ? `${label.slice(0, 29)}…` : label;
        }

        function polarPoint(angle, radius) {
            const adjusted = angle - Math.PI / 2;
            return [Math.cos(adjusted) * radius, Math.sin(adjusted) * radius];
        }

        function transformFor(datum) {
            const [x, y] = polarPoint(datum.x, datum.y);
            return `translate(${x},${y})`;
        }

        function selectedPathIds() {
            const selected = nodes.get(selectedId);
            return new Set(selected ? ["visual-root", ...selected.path.map(part => part.id)] : []);
        }

        function relatedBranchIds() {
            if (!selectedId) return new Set();
            const related = new Set(selectedPathIds());
            const selectedHierarchyNode = positions.get(selectedId);
            if (selectedHierarchyNode) selectedHierarchyNode.descendants().forEach(item => related.add(item.data.id));
            return related;
        }

        function updateClasses() {
            const path = selectedPathIds();
            const related = relatedBranchIds();
            nodesLayer.selectAll("g.radial-node")
                .classed("is-selected", datum => datum.data.id === selectedId)
                .classed("is-ancestor", datum => path.has(datum.data.id) && datum.data.id !== selectedId)
                .classed("is-dimmed", datum => Boolean(selectedId) && !related.has(datum.data.id));
            linksLayer.selectAll("path.radial-link")
                .classed("is-ancestor", link => path.has(link.source.data.id) && path.has(link.target.data.id))
                .classed("is-dimmed", link => Boolean(selectedId) && !related.has(link.target.data.id));
        }

        function labelTransform(datum) {
            if (datum.data.type === "root") return "translate(0,-21)";
            const degrees = datum.x * 180 / Math.PI - 90;
            const typeOffset = { spectrum: 11, subfactor: 9, scale: 8, question: 6 }[datum.data.type] || 7;
            const collisionOffset = (datum.labelLane || 0) * 15;
            return `rotate(${degrees}) translate(${radiusFor(datum) + typeOffset + collisionOffset},0)${datum.x >= Math.PI ? " rotate(180)" : ""}`;
        }

        function assignLabelLanes(hierarchy, radius) {
            const maxDepth = Math.max(1, hierarchy.height);
            const byDepth = d3.group(
                hierarchy.descendants().filter(datum => datum.data.type !== "root"),
                datum => datum.depth,
            );
            byDepth.forEach((level, depth) => {
                const levelRadius = radius * depth / maxDepth;
                const ordered = level.slice().sort((a, b) => a.x - b.x);
                ordered.forEach((datum, index) => {
                    datum.labelLane = 0;
                    datum.labelCollision = false;
                    if (!index) return;
                    const previous = ordered[index - 1];
                    const angularDistance = (datum.x - previous.x) * levelRadius;
                    const minimumDistance = datum.data.type === "scale" ? 15 : 19;
                    if (angularDistance < minimumDistance) {
                        datum.labelLane = previous.labelLane === 0 ? 1 : 0;
                        datum.labelCollision = (
                            datum.data.type === "scale"
                            && index > 1
                            && (datum.x - ordered[index - 2].x) * levelRadius < 14
                        );
                    }
                });
            });
        }

        function tooltipLines(datum) {
            const node = datum.data;
            if (node.type === "root") return ["HiTOP", questionCountLabel(node.question_count)];
            const lines = [node.label || node.name, node.type_label];
            if (node.type === "question") {
                const scale = node.path.find(part => part.type === "scale");
                if (scale) lines.push(`Escala: ${scale.label || scale.name}`);
            } else {
                lines.push(questionCountLabel(node.question_count));
                if (node.type === "scale") {
                    const subfactor = node.path.find(part => part.type === "subfactor");
                    if (subfactor) lines.push(`Subfator: ${subfactor.label || subfactor.name}`);
                }
            }
            if (node.issues.length) lines.push(node.issues[0].title);
            return lines;
        }

        function showTooltip(event, datum) {
            tooltip.selectAll("*").remove();
            tooltipLines(datum).forEach((line, index) => tooltip.append(index === 0 ? "strong" : "span").text(line));
            const bounds = root.getBoundingClientRect();
            tooltip.classed("is-visible", true).style("left", `${event.clientX - bounds.left + 14}px`).style("top", `${event.clientY - bounds.top + 14}px`);
        }

        function activateNode(event, datum) {
            event.stopPropagation();
            if (datum.data.type === "root") {
                clearSelection({ collapseExpansions: true });
                return;
            }
            selectNode(datum.data.id, {
                focusTree: false,
                focusVisual: false,
                toggleScale: datum.data.type === "scale",
            });
        }

        function setExpandedScale(scaleId) {
            const nextScales = scaleId ? [scaleId] : [];
            if (openScales.size === nextScales.length && nextScales.every(id => openScales.has(id))) return false;
            openScales.clear();
            nextScales.forEach(id => openScales.add(id));
            return true;
        }

        function update({ animate = true } = {}) {
            if (!isVisible()) return;
            const hierarchy = d3.hierarchy(hierarchyData(), visualChildren);
            const descendants = hierarchy.descendants();
            const leaves = hierarchy.leaves();
            const structuralLabels = descendants.filter(item => item.data.type !== "question");
            const labelDemand = d3.sum(structuralLabels, item => Math.min(34, item.data.name.length));
            const availableRadius = Math.max(260, Math.min(width, height) * 0.48);
            const radius = Math.max(availableRadius, Math.min(760,
                250 + Math.sqrt(descendants.length) * 18,
                230 + leaves.length * 3.9,
                260 + labelDemand * 0.42,
            ));
            const maximumDepth = Math.max(1, hierarchy.height);
            const baseAngle = (2 * Math.PI) / Math.max(1, leaves.length);
            d3.tree()
                .size([2 * Math.PI, radius])
                .separation((a, b) => {
                    const depth = Math.max(1, Math.min(a.depth, b.depth));
                    const levelRadius = Math.max(54, radius * depth / maximumDepth);
                    const labelAngle = (
                        estimatedLabelWidth(a) + estimatedLabelWidth(b) + 18
                    ) / (2 * levelRadius);
                    const densitySpacing = labelAngle / baseAngle;
                    const relationshipSpacing = a.parent === b.parent ? 1 : 1.55;
                    const priority = depth <= 2 ? 1.35 : depth === 3 ? 1.08 : 1;
                    return Math.max(relationshipSpacing, densitySpacing * priority);
                })(hierarchy);
            assignLabelLanes(hierarchy, radius);
            positions.clear();
            descendants.forEach(item => positions.set(item.data.id, item));
            const duration = animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 280 : 0;
            const transition = svg.transition().duration(duration).ease(d3.easeCubicOut);
            const radialLink = d3.linkRadial().angle(item => item.x).radius(item => item.y);
            linksLayer.selectAll("path.radial-link")
                .data(hierarchy.links(), link => link.target.data.id)
                .join(
                    enter => enter.append("path").attr("class", "radial-link").attr("d", link => radialLink({ source: link.source, target: link.source })).attr("stroke", link => colorFor(link.target)).call(selection => selection.transition(transition).attr("d", radialLink)),
                    updateSelection => updateSelection.attr("stroke", link => colorFor(link.target)).call(selection => selection.transition(transition).attr("d", radialLink)),
                    exit => exit.transition(transition).style("opacity", 0).remove(),
                );
            const nodeJoin = nodesLayer.selectAll("g.radial-node")
                .data(descendants, datum => datum.data.id)
                .join(
                    enter => {
                        const group = enter.append("g")
                            .attr("class", datum => `radial-node radial-${datum.data.type}`)
                            .attr("transform", datum => transformFor(datum.parent || datum))
                            .attr("role", datum => datum.data.type === "root" ? null : "button")
                            .attr("tabindex", datum => datum.data.type === "root" ? null : 0)
                            .attr("aria-label", datum => `${datum.data.type_label}: ${datum.data.label || datum.data.name}`)
                            .on("click", activateNode)
                            .on("keydown", (event, datum) => {
                                if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activateNode(event, datum); }
                            })
                            .on("pointerenter pointermove", showTooltip)
                            .on("pointerleave", () => tooltip.classed("is-visible", false));
                        group.append("circle").attr("class", "radial-node-halo");
                        group.append("circle").attr("class", "radial-node-mark");
                        group.append("text").attr("class", "radial-node-label");
                        group.filter(datum => datum.data.issues.length).append("text").attr("class", "radial-warning-mark").attr("aria-hidden", "true").text("!");
                        return group;
                    },
                    updateSelection => updateSelection,
                    exit => exit.transition(transition).style("opacity", 0).remove(),
                );
            nodeJoin.attr("class", datum => `radial-node radial-${datum.data.type}${datum.data.issues.length ? " has-warning" : ""}${datum.labelCollision ? " label-collision" : ""}`).call(selection => selection.transition(transition).attr("transform", transformFor));
            nodeJoin.select("circle.radial-node-halo").attr("r", datum => radiusFor(datum) + 5);
            nodeJoin.select("circle.radial-node-mark").attr("r", radiusFor).attr("fill", fillFor).attr("stroke", colorFor);
            nodeJoin.select("text.radial-node-label").text(visibleLabel).attr("text-anchor", datum => datum.data.type === "root" ? "middle" : datum.x < Math.PI ? "start" : "end").attr("transform", labelTransform);
            nodeJoin.select("text.radial-warning-mark").attr("x", datum => radiusFor(datum) + 5).attr("y", datum => -(radiusFor(datum) + 3));
            updateClasses();
            if (firstVisibleRender) {
                firstVisibleRender = false;
                requestAnimationFrame(() => fit(false));
            }
        }

        function fit(animate = true) {
            if (!isVisible()) return;
            // Fit the radial geometry, not long labels, so the hierarchy uses
            // the available viewport while labels may extend into its padding.
            const content = linksLayer.node().getBBox();
            if (!content.width || !content.height) return;
            const padding = 54;
            const scale = Math.max(0.35, Math.min(1.35, (width - padding * 2) / content.width, (height - padding * 2) / content.height));
            const transform = d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-(content.x + content.width / 2), -(content.y + content.height / 2));
            svg.transition().duration(animate ? 320 : 0).call(zoom.transform, transform);
        }

        function focusNode(id) {
            const datum = positions.get(id);
            if (!datum || !isVisible()) return;
            const [x, y] = polarPoint(datum.x, datum.y);
            const scale = Math.max(1.15, Math.min(2.2, currentZoom.k));
            svg.transition().duration(420).call(zoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-x, -y));
        }

        function isVisible() {
            return !root.querySelector("#visual-panel").hidden;
        }

        new ResizeObserver(entries => {
            const bounds = entries[0].contentRect;
            if (!bounds.width || !bounds.height) return;
            width = bounds.width;
            height = bounds.height;
            svg.attr("viewBox", `0 0 ${width} ${height}`);
            if (isVisible()) update({ animate: false });
        }).observe(visualContainer);

        return {
            update,
            fit,
            focusNode,
            isVisible,
            refreshSelection: updateClasses,
            collapseAll: () => setExpandedScale(null),
            syncExpansionForSelection: (node, toggleScale) => {
                if (node.type === "question") return setExpandedScale(node.parentId);
                if (node.type === "scale" && toggleScale) {
                    return setExpandedScale(openScales.has(node.id) ? null : node.id);
                }
                return setExpandedScale(null);
            },
            zoomBy: factor => svg.transition().duration(220).call(zoom.scaleBy, factor),
        };
    }

    const radialMap = createRadialMap();
    root.querySelector("[data-expand-all]").addEventListener("click", () => { nodes.forEach(node => { if (node.children.length) expanded.add(node.id); }); renderTree(); });
    root.querySelector("[data-collapse-all]").addEventListener("click", () => { expanded.clear(); renderTree(); });
    root.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
        currentFilter = button.dataset.filter;
        root.querySelectorAll("[data-filter]").forEach(peer => { const active = peer === button; peer.classList.toggle("active", active); peer.setAttribute("aria-pressed", String(active)); });
        renderTree();
        radialMap.update();
    }));
    root.querySelectorAll("[role=tab]").forEach(tab => tab.addEventListener("click", () => {
        root.querySelectorAll("[role=tab]").forEach(peer => { const active = peer === tab; peer.classList.toggle("active", active); peer.setAttribute("aria-selected", String(active)); document.getElementById(peer.getAttribute("aria-controls")).hidden = !active; });
        if (tab.id === "visual-tab") requestAnimationFrame(() => { radialMap.update({ animate: false }); selectedId ? radialMap.focusNode(selectedId) : radialMap.fit(false); });
    }));
    searchInput.addEventListener("input", search);
    searchInput.addEventListener("keydown", event => {
        if (event.key === "Escape") { searchResults.hidden = true; searchInput.value = ""; }
        if (event.key === "Enter") searchResults.querySelector("button")?.click();
    });
    document.addEventListener("click", event => { if (!event.target.closest(".map-search-wrap")) searchResults.hidden = true; });
    root.querySelector("[data-zoom-in]").addEventListener("click", () => radialMap.zoomBy(1.25));
    root.querySelector("[data-zoom-out]").addEventListener("click", () => radialMap.zoomBy(0.8));
    root.querySelector("[data-zoom-fit]").addEventListener("click", () => radialMap.fit());
    renderTree();
    radialMap.update({ animate: false });
})();
