# Placeholder rag
import regex as re
import tiktoken  #type:ignore

TOKENIZER = tiktoken.get_encoding("cl100k_base")
CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50

def _token_len(txt : str) -> int:
    return(len(TOKENIZER.encode(txt)))

def split_text(raw: str) -> list[str]:
    """Generate and return a list of overlapping chunks(500 tok each)

    Args:
        raw (str): _description_

    Returns:
        list[str]: _description_
    """
    # Split by sentences
    sentences = re.split(r'(?<=[.!?])\s+' , raw)
    
    # Greedy packing - keep adding sentences untill we reach the token limit
    
    current = []
    cur_len =0
    chunks = []
    
    for s in sentences:
        s_len = _token_len(s)
        if cur_len + s_len > CHUNK_TOKENS:
            chunks.append("".join(current).strip())
            
            overlap = " ".join(current[-OVERLAP_TOKENS:])
            
            current = [overlap, s] if overlap else [s]
            cur_len = _token_len(" ".join(current))
        else:
            current.append(s)
            cur_len += s_len
    if current:
        chunks.append(" ".join(current).strip())
    return chunks