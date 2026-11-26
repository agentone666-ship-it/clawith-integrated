import { useEffect, useLayoutEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { IconCheck, IconPointer, IconX } from '@tabler/icons-react';
import './modelSettingsGuide.css';

export interface ModelSettingsGuideContext {
    startModelSettingsGuide: () => void;
}

interface Props {
    pathname: string;
    hash: string;
    menuOpen: boolean;
    isChinese: boolean;
    onDismiss: () => void;
}

interface Position {
    spot: { left: number; top: number; width: number; height: number };
    card: { left: number; top: number };
}

const STEPS = [
    { selector: '[data-tour-target="company-switcher"] button', title: '先点击左上角的公司名称',
        body: '公司设置在这个菜单里。请点击高亮的公司名称，展开菜单。',
        enTitle: 'Click your company name', enBody: 'Company settings live in this menu. Click the highlighted company name to open it.' },
    { selector: '[data-tour-target="company-settings"]', title: '再点击「公司信息设置」',
        body: '这就是公司设置的原入口。请点击高亮的「公司信息设置」。',
        enTitle: 'Click Company settings', enBody: 'This is the original settings entry. Click the highlighted Company settings option.' },
    { selector: '[data-tour-target="model-pool"]', title: '最后点击「模型池」',
        body: '在这里添加和管理模型。请点击高亮的「模型池」，完成这次引导。',
        enTitle: 'Open the Model pool', enBody: 'Add and manage models here. Click the highlighted Model pool tab to finish the walkthrough.' },
] as const;

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, Math.max(min, max)));

export function ModelSettingsGuide({ pathname, hash, menuOpen, isChinese, onDismiss }: Props) {
    const inSettings = pathname === '/enterprise';
    const complete = inSettings && hash === '#llm';
    const step = inSettings ? 2 : menuOpen ? 1 : 0;
    const current = STEPS[step];
    const [position, setPosition] = useState<Position | null>(null);

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onDismiss(); };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [onDismiss]);

    useEffect(() => {
        if (!pathname.startsWith('/recruitment') && !inSettings) onDismiss();
    }, [pathname, inSettings, onDismiss]);

    useLayoutEffect(() => {
        let frame = 0;
        let target: HTMLElement | null = null;
        let previousPosition: Position | null | undefined;
        const publishPosition = (next: Position | null) => {
            if (previousPosition !== undefined &&
                (previousPosition === next || (previousPosition && next &&
                    previousPosition.spot.left === next.spot.left && previousPosition.spot.top === next.spot.top &&
                    previousPosition.spot.width === next.spot.width && previousPosition.spot.height === next.spot.height &&
                    previousPosition.card.left === next.card.left && previousPosition.card.top === next.card.top))) return;
            previousPosition = next;
            setPosition(next);
        };
        const update = () => {
            const element = target?.isConnected ? target : document.querySelector<HTMLElement>(current.selector);
            if (!element) { publishPosition(null); return; }
            if (target !== element) {
                target = element;
                element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                element.focus({ preventScroll: true });
            }
            const rect = element.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) { publishPosition(null); return; }
            const width = window.innerWidth;
            const height = window.innerHeight;
            const cardWidth = Math.min(320, width - 24);
            const spot = { left: Math.max(4, rect.left - 5), top: Math.max(4, rect.top - 5),
                width: Math.min(rect.width + 10, width - 8), height: Math.min(rect.height + 10, height - 8) };
            const right = spot.left + spot.width + 18;
            const cardLeft = right + cardWidth <= width - 12 ? right : clamp(spot.left, 12, width - cardWidth - 12);
            const cardTop = right + cardWidth <= width - 12 ? spot.top : spot.top + spot.height + 18;
            publishPosition({ spot, card: { left: cardLeft, top: clamp(cardTop, 12, height - 240) } });
        };
        const trackPosition = () => {
            // Ancestor transforms move the target without triggering ResizeObserver.
            update();
            frame = requestAnimationFrame(trackPosition);
        };
        frame = requestAnimationFrame(trackPosition);
        return () => cancelAnimationFrame(frame);
    }, [current.selector]);

    const title = complete ? (isChinese ? '你已经找到模型池了' : 'You found the Model pool') : isChinese ? current.title : current.enTitle;
    const body = complete ? (isChinese ? '下次从「左上角公司名称 → 公司信息设置 → 模型池」进入即可。现在可以添加模型了。' : 'Next time, follow Company name → Company settings → Model pool. You can now add a model.') : isChinese ? current.body : current.enBody;
    return createPortal(<div className="company-tour-overlay model-settings-guide" aria-label={isChinese ? '模型设置入口引导' : 'Model settings walkthrough'}>
        {position && <div className="tour-spot model-settings-guide-spot" style={position.spot} />}
        <div className="model-settings-guide-card" role="dialog" aria-modal="false" aria-labelledby="model-guide-title"
            onMouseDown={event => event.stopPropagation()}
            style={position?.card || { left: 16, bottom: 20 }}>
            <div className="model-settings-guide-heading"><span>{complete ? <IconCheck size={14} /> : <IconPointer size={14} />}{step + 1} / 3</span>
                <button className="btn btn-ghost" onClick={onDismiss} aria-label={isChinese ? '关闭设置引导' : 'Close walkthrough'}><IconX size={15} /></button></div>
            <h3 id="model-guide-title">{position ? title : isChinese ? '正在定位入口…' : 'Locating the entry…'}</h3>
            <p aria-live="polite">{body}</p>
            <div className="model-settings-guide-footer"><span>{complete ? (isChinese ? '入口已找到' : 'Entry found') : (isChinese ? '请直接点击高亮位置' : 'Click the highlighted item')}</span>
                <button className={`btn ${complete ? 'btn-primary' : 'btn-ghost'}`} onClick={onDismiss}>{complete ? (isChinese ? '完成引导' : 'Done') : (isChinese ? '退出引导' : 'Exit guide')}</button></div>
        </div>
    </div>, document.body);
}
