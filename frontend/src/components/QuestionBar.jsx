import { sample } from '../data/sample.js';

const box =
  'flex items-center justify-center rounded-[10px] border-[1.6px] border-line bg-white p-0 text-ink';

export default function QuestionBar({ question, rounds, modelLabel, running, onQuestion, onRounds, onModel, onStart }) {
  const modelText = `Model: ${modelLabel}`;
  return (
    <div className="absolute left-[24px] top-[104px] flex h-[48px] w-[974px] items-stretch">
      <input
        type="text"
        value={question}
        readOnly={running}
        maxLength={2000}
        spellCheck={false}
        aria-label="Question"
        onChange={(e) => onQuestion(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && onStart()}
        className={`w-[600px] rounded-[10px] border-[1.6px] border-line bg-panel px-[16px] text-[16.4px] outline-none focus:border-muted ${
          question === sample.question ? 'text-muted' : 'text-ink'
        }`}
      />
      <button
        type="button"
        disabled={running}
        onClick={onRounds}
        title="Click to change the number of rounds"
        className={`${box} ml-[16px] w-[124px] text-[15.6px] ${running ? 'cursor-default' : 'cursor-pointer hover:bg-panel'}`}
      >
        Rounds: {rounds}
      </button>
      <button
        type="button"
        disabled={running}
        onClick={onModel}
        title="Click to change the model"
        className={`${box} ml-[12px] w-[124px] px-[6px] ${running ? 'cursor-default' : 'cursor-pointer hover:bg-panel'}`}
      >
        <span className={`truncate ${modelText.length > 13 ? 'text-[12.5px]' : 'text-[15.6px]'}`}>{modelText}</span>
      </button>
      <button
        type="button"
        onClick={onStart}
        className="ml-[12px] flex w-[86px] cursor-pointer items-center justify-center rounded-[10px] border-0 bg-teal p-0 text-[16px] font-bold text-white hover:brightness-95"
      >
        {running ? 'Stop' : 'Start'}
      </button>
    </div>
  );
}
